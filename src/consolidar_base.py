"""Consolida as bases de queimadas, MapBiomas e BDMEP numa grade município × dia.

A base de queimadas só registra onde o satélite viu fogo. Para o modelo aprender
também o risco baixo, a grade inclui todos os municípios em todos os dias, e o
dia sem foco vale zero (viés de sobrevivência, ver 01_eda.ipynb).

Cada passo é uma consulta SQL no DuckDB, para o notebook de EDA poder mostrar o
efeito de cada um. Rodar este arquivo direto executa todos os passos e salva a
base processada:

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
    con = duckdb.connect()
    con.execute(f"CREATE VIEW queimadas AS SELECT * FROM read_csv('{BRUTOS / 'queimadas_2024_2025.csv'}', delim=';', header=true)")
    con.execute(f"CREATE VIEW mapbiomas AS SELECT * FROM read_csv('{BRUTOS / 'MapBiomas.csv'}', header=true)")
    con.execute(f"CREATE VIEW bdmep AS SELECT * FROM read_csv('{BRUTOS / 'BDMEP-2025.csv'}', header=true)")
    con.execute(f"CREATE VIEW estacoes AS SELECT * FROM read_csv('{BRUTOS / 'BDMEP-estacao.csv'}', header=true)")
    return con


def _lista(codigos):
    return ', '.join(str(c) for c in codigos)


def contar_focos(con):
    """Focos de satélites polares por município e dia, sem os focos duplicados."""
    con.execute(f"""
        CREATE OR REPLACE TABLE focos_dia AS
        SELECT id_municipio, CAST(data_hora AS DATE) AS dia,
               count(DISTINCT (data_hora, latitude, longitude, satelite)) AS focos
        FROM queimadas
        WHERE satelite NOT IN {GEOESTACIONARIOS}
        GROUP BY 1, 2
    """)


def montar_grade(con):
    """Todos os municípios do MapBiomas × todos os dias do período, com zero no dia sem foco."""
    con.execute("""
        CREATE OR REPLACE TABLE grade AS
        WITH municipios AS (SELECT DISTINCT id_municipio, sigla_uf FROM mapbiomas),
             periodo AS (SELECT min(CAST(data_hora AS DATE)) AS ini, max(CAST(data_hora AS DATE)) AS fim FROM queimadas),
             dias AS (SELECT CAST(d AS DATE) AS dia
                      FROM periodo, range(periodo.ini, periodo.fim + INTERVAL 1 DAY, INTERVAL 1 DAY) t(d))
        SELECT m.id_municipio, m.sigla_uf, d.dia, coalesce(f.focos, 0) AS focos
        FROM municipios m CROSS JOIN dias d
        LEFT JOIN focos_dia f USING (id_municipio, dia)
    """)


def criar_historico(con):
    """Focos dos dias anteriores. Só usa o passado: o dia da previsão fica fora da janela."""
    con.execute("""
        CREATE OR REPLACE TABLE grade AS
        SELECT *,
            lag(focos, 1) OVER w AS focos_ontem,
            sum(focos) OVER (w ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS focos_7d,
            sum(focos) OVER (w ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) AS focos_30d,
            sum((focos > 0)::INT) OVER (w ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) AS dias_com_foco_30d,
            row_number() OVER w AS dia_da_serie
        FROM grade
        WINDOW w AS (PARTITION BY id_municipio ORDER BY dia)
    """)


def criar_calendario(con):
    con.execute("""
        CREATE OR REPLACE TABLE grade AS
        SELECT *, month(dia) AS mes, dayofyear(dia) AS dia_do_ano FROM grade
    """)


def criar_uso_do_solo(con):
    """Proporção de cada grupo do MapBiomas em 2021 e a perda de vegetação nativa entre 2016 e 2021."""
    colunas = ',\n'.join(
        f"coalesce(sum(area) FILTER (WHERE id_classe IN ({_lista(codigos)})), 0) / sum(area) AS pct_{grupo}"
        for grupo, codigos in GRUPOS_MAPBIOMAS.items())
    con.execute(f"""
        CREATE OR REPLACE TABLE uso_solo AS
        WITH ano_2021 AS (
            SELECT id_municipio, sum(area) AS area_km2, {colunas}
            FROM mapbiomas WHERE ano = 2021 GROUP BY 1),
        nativa AS (
            SELECT id_municipio,
                sum(area) FILTER (WHERE ano = 2016 AND id_classe IN ({_lista(NATIVOS)})) AS nativa_2016,
                sum(area) FILTER (WHERE ano = 2021 AND id_classe IN ({_lista(NATIVOS)})) AS nativa_2021
            FROM mapbiomas GROUP BY 1)
        SELECT a.*, coalesce((n.nativa_2016 - n.nativa_2021) / a.area_km2, 0) AS perda_nativa_5a
        FROM ano_2021 a LEFT JOIN nativa n USING (id_municipio)
    """)
    con.execute("""
        CREATE OR REPLACE TABLE grade AS
        SELECT g.*, u.* EXCLUDE (id_municipio) FROM grade g LEFT JOIN uso_solo u USING (id_municipio)
    """)


def criar_alvo(con):
    """Nível de risco do dia: Baixo (sem foco), Médio (1 a 3 focos), Alto (4 ou mais)."""
    con.execute(f"""
        CREATE OR REPLACE TABLE grade AS
        SELECT *, CASE WHEN focos >= {CORTE_ALTO} THEN 'Alto'
                       WHEN focos >= {CORTE_MEDIO} THEN 'Médio'
                       ELSE 'Baixo' END AS nivel_risco
        FROM grade
    """)


def remover_sem_historico(con):
    con.execute(f"""
        CREATE OR REPLACE TABLE grade AS
        SELECT * EXCLUDE (dia_da_serie) FROM grade WHERE dia_da_serie > {DIAS_SEM_HISTORICO}
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
