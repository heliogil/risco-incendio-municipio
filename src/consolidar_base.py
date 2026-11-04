"""Consolida as bases de queimadas, MapBiomas e BDMEP numa grade município × dia.

A base de queimadas só registra onde o satélite viu fogo. Para o modelo aprender
também o risco baixo, a grade inclui todos os municípios em todos os dias, e o
dia sem foco vale zero (viés de sobrevivência, ver 01_eda.ipynb).

Cada passo é uma consulta SQL no DuckDB, comentada linha por linha. Cada função
roda a sua consulta e devolve o texto dela, para o notebook de EDA poder mostrar
a consulta e o efeito de cada passo. Rodar este arquivo direto executa todos os
passos e salva a base processada:

    python src/consolidar_base.py
"""
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent.parent
BRUTOS = RAIZ / 'dados' / 'brutos'
ARQUIVO_PROCESSADO = RAIZ / 'dados' / 'processado' / 'grade_municipio_dia.parquet'

# Satélites geoestacionários fotografam a cada poucos minutos e repetem o mesmo
# fogo; a contagem usa só os de órbita polar.
GEOESTACIONARIOS = ('GOES-16', 'MSG-03')

# Cortes do alvo, em focos de satélites polares no município e no dia.
CORTE_MEDIO = 1
CORTE_ALTO = 4

# Os primeiros 30 dias não têm histórico de 30 dias para trás e ficam fora.
DIAS_SEM_HISTORICO = 30

# Grupos da legenda oficial do MapBiomas (Coleção 8).
GRUPOS_MAPBIOMAS = {
    'floresta': (3, 4, 5, 6, 49),
    'natural_nao_florestal': (11, 12, 13, 29, 32, 50),
    'pastagem': (15,),
    'agricultura': (9, 20, 35, 39, 40, 41, 46, 47, 48, 62),
    'mosaico': (21,),
    'nao_vegetada': (23, 24, 25, 30),
    'agua': (31, 33),
}
NATIVOS = GRUPOS_MAPBIOMAS['floresta'] + GRUPOS_MAPBIOMAS['natural_nao_florestal']


def conectar():
    """Abre o DuckDB e cria uma "visão" (um atalho com nome) para cada CSV bruto."""
    con = duckdb.connect()
    con.execute(f"CREATE VIEW queimadas AS SELECT * FROM read_csv('{BRUTOS / 'queimadas_2024_2025.csv'}', delim=';', header=true)")
    con.execute(f"CREATE VIEW mapbiomas AS SELECT * FROM read_csv('{BRUTOS / 'MapBiomas.csv'}', header=true)")
    con.execute(f"CREATE VIEW bdmep AS SELECT * FROM read_csv('{BRUTOS / 'BDMEP-2025.csv'}', header=true)")
    con.execute(f"CREATE VIEW estacoes AS SELECT * FROM read_csv('{BRUTOS / 'BDMEP-estacao.csv'}', header=true)")
    return con


def _lista(codigos):
    return ', '.join(str(c) for c in codigos)


def _rodar(con, sql):
    con.execute(sql)
    return sql.strip()


def contar_focos(con):
    """Passo 1: quantos focos cada município teve em cada dia."""
    return _rodar(con, f"""
-- Cria a tabela focos_dia: uma linha por município e dia que teve fogo.
CREATE OR REPLACE TABLE focos_dia AS
SELECT
    id_municipio,
    CAST(data_hora AS DATE) AS dia,           -- tira a hora e fica só a data
    COUNT(DISTINCT (data_hora, latitude, longitude, satelite)) AS focos
                                              -- conta focos diferentes (repetidos contam uma vez)
FROM queimadas
WHERE satelite NOT IN {GEOESTACIONARIOS}      -- deixa de fora os satélites que repetem o mesmo fogo
GROUP BY id_municipio, dia                    -- junta tudo do mesmo município no mesmo dia
""")


def montar_grade(con):
    """Passo 2: todos os municípios em todos os dias, com zero no dia sem foco."""
    return _rodar(con, """
-- Cria a tabela grade: uma linha para cada município em cada dia do período.
CREATE OR REPLACE TABLE grade AS
WITH
    -- a lista de municípios, tirada do MapBiomas
    municipios AS (SELECT DISTINCT id_municipio, sigla_uf FROM mapbiomas),
    -- a lista de todos os dias, do primeiro ao último dia com foco na base
    dias AS (
        SELECT CAST(dia AS DATE) AS dia
        FROM generate_series(
            (SELECT MIN(CAST(data_hora AS DATE)) FROM queimadas),
            (SELECT MAX(CAST(data_hora AS DATE)) FROM queimadas),
            INTERVAL 1 DAY) AS t(dia)
    )
SELECT
    m.id_municipio,
    m.sigla_uf,
    d.dia,
    COALESCE(f.focos, 0) AS focos             -- se o dia não teve foco, vale 0
FROM municipios m
CROSS JOIN dias d                             -- combina cada município com cada dia
LEFT JOIN focos_dia f                         -- traz os focos do passo 1, quando existem
    ON f.id_municipio = m.id_municipio AND f.dia = d.dia
""")


def criar_historico(con):
    """Passo 3: os focos dos dias anteriores. O próprio dia nunca entra na conta."""
    return _rodar(con, """
-- Acrescenta à grade o histórico de focos de cada município.
-- "OVER (PARTITION BY ... ORDER BY ...)" é uma função de janela: para cada linha,
-- olha as outras linhas do MESMO município, em ordem de data.
CREATE OR REPLACE TABLE grade AS
SELECT
    *,
    LAG(focos, 1) OVER janela AS focos_ontem, -- o valor de focos na linha anterior (ontem)
    SUM(focos) OVER (janela ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS focos_7d,
                                              -- soma dos 7 dias anteriores (sem hoje)
    SUM(focos) OVER (janela ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) AS focos_30d,
                                              -- soma dos 30 dias anteriores (sem hoje)
    SUM(CASE WHEN focos > 0 THEN 1 ELSE 0 END)
        OVER (janela ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) AS dias_com_foco_30d,
                                              -- quantos dos 30 dias anteriores tiveram fogo
    ROW_NUMBER() OVER janela AS dia_da_serie  -- 1 no primeiro dia, 2 no segundo... (usado no passo 7)
FROM grade
WINDOW janela AS (PARTITION BY id_municipio ORDER BY dia)
""")


def criar_calendario(con):
    """Passo 4: o mês e o dia do ano, porque o fogo tem estação."""
    return _rodar(con, """
CREATE OR REPLACE TABLE grade AS
SELECT
    *,
    MONTH(dia) AS mes,                        -- 1 a 12
    DAYOFYEAR(dia) AS dia_do_ano              -- 1 a 366
FROM grade
""")


def criar_uso_do_solo(con):
    """Passo 5: o uso do solo de cada município (MapBiomas 2021) e a perda de vegetação nativa."""
    colunas = ',\n'.join(
        f"    SUM(CASE WHEN ano = 2021 AND id_classe IN ({_lista(codigos)}) THEN area ELSE 0 END)\n"
        f"        / SUM(CASE WHEN ano = 2021 THEN area ELSE 0 END) AS pct_{grupo}"
        for grupo, codigos in GRUPOS_MAPBIOMAS.items())
    nativos = _lista(NATIVOS)
    return _rodar(con, f"""
-- Primeiro, uma tabela com uma linha por município.
CREATE OR REPLACE TABLE uso_solo AS
SELECT
    id_municipio,
    SUM(CASE WHEN ano = 2021 THEN area ELSE 0 END) AS area_km2,
                                              -- área total do município em 2021
    -- para cada grupo: área do grupo em 2021 ÷ área total = proporção de 0 a 1
{colunas},
    -- perda de vegetação nativa: (área nativa em 2016 - área nativa em 2021) ÷ área total
    (SUM(CASE WHEN ano = 2016 AND id_classe IN ({nativos}) THEN area ELSE 0 END)
     - SUM(CASE WHEN ano = 2021 AND id_classe IN ({nativos}) THEN area ELSE 0 END))
        / SUM(CASE WHEN ano = 2021 THEN area ELSE 0 END) AS perda_nativa_5a
FROM mapbiomas
GROUP BY id_municipio;

-- Depois, essas colunas são coladas em todas as linhas (todos os dias) do município.
CREATE OR REPLACE TABLE grade AS
SELECT g.*, u.area_km2, {', '.join(f'u.pct_{g}' for g in GRUPOS_MAPBIOMAS)}, u.perda_nativa_5a
FROM grade g
LEFT JOIN uso_solo u ON u.id_municipio = g.id_municipio
""")


def criar_alvo(con):
    """Passo 6: o nível de risco do dia, a partir do número de focos."""
    return _rodar(con, f"""
CREATE OR REPLACE TABLE grade AS
SELECT
    *,
    CASE
        WHEN focos >= {CORTE_ALTO} THEN 'Alto'      -- 4 ou mais focos
        WHEN focos >= {CORTE_MEDIO} THEN 'Médio'    -- 1 a 3 focos
        ELSE 'Baixo'                         -- nenhum foco
    END AS nivel_risco
FROM grade
""")


def remover_sem_historico(con):
    """Passo 7: tira os primeiros 30 dias, que não têm 30 dias de passado."""
    return _rodar(con, f"""
CREATE OR REPLACE TABLE grade AS
SELECT * EXCLUDE (dia_da_serie)               -- todas as colunas, menos a auxiliar do passo 3
FROM grade
WHERE dia_da_serie > {DIAS_SEM_HISTORICO}                 -- só a partir do 31º dia da série
ORDER BY id_municipio, dia
""")


PASSOS = [contar_focos, montar_grade, criar_historico, criar_calendario,
          criar_uso_do_solo, criar_alvo, remover_sem_historico]


def preparar(con):
    for passo in PASSOS:
        passo(con)
    return con


def salvar(con, caminho=ARQUIVO_PROCESSADO):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY grade TO '{caminho.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
    return caminho


if __name__ == '__main__':
    con = preparar(conectar())
    destino = salvar(con)
    linhas = con.execute('SELECT count(*) FROM grade').fetchone()[0]
    colunas = len(con.execute('SELECT * FROM grade LIMIT 0').description)
    print(f'{linhas} linhas e {colunas} colunas salvas em {destino}')
