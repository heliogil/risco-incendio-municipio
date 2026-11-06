"""Consolida as bases de queimadas, MapBiomas e clima numa grade município × dia.

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
INMET_2024 = BRUTOS / 'inmet_2024'
MUNICIPIOS = RAIZ / 'dados' / 'externos' / 'municipios.csv'
ARQUIVO_PROCESSADO = RAIZ / 'dados' / 'processado' / 'grade_municipio_dia.parquet'
ARQUIVO_SEM_CLIMA = RAIZ / 'dados' / 'processado' / 'linhas_sem_clima_por_municipio.csv'

# Clima: um valor diário só vale se a estação mediu pelo menos 18 das 24 horas.
HORAS_MINIMAS = 18
# Cada município usa as estações a até 400 km da sede, no máximo as 10 mais próximas.
DISTANCIA_MAXIMA_KM = 400
ESTACOES_POR_MUNICIPIO = 10

# Colunas dos CSVs do INMET 2024, na ordem do arquivo.
COLUNAS_INMET = ['data', 'hora', 'chuva', 'pressao', 'pressao_max', 'pressao_min', 'radiacao', 'temperatura',
                 'orvalho', 'temp_max', 'temp_min', 'orvalho_max', 'orvalho_min', 'umidade_max',
                 'umidade_min', 'umidade', 'vento_direcao', 'rajada', 'vento', 'vazia']

# Satélites geoestacionários fotografam a cada poucos minutos e repetem o mesmo
# fogo; a contagem usa só os de órbita polar.
GEOESTACIONARIOS = ('GOES-16', 'MSG-03')

# Limites do alvo, em focos de satélites polares no município e no dia.
CORTE_MEDIO = 1
CORTE_ALTO = 4

# Os primeiros 30 dias não têm histórico de 30 dias para trás e ficam fora.
DIAS_SEM_HISTORICO = 30

# Grupos da legenda oficial do MapBiomas, Coleção 7 (a que cobre 1985 a 2021, como o arquivo fornecido).
GRUPOS_MAPBIOMAS = {
    'floresta': (3, 4, 5, 49),
    'natural_nao_florestal': (11, 12, 13, 29, 32, 50),
    'pastagem': (15,),
    'agricultura': (9, 20, 39, 40, 41, 46, 47, 48, 62),
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
    # INMET 2024: um CSV por estação, com 9 linhas de cabeçalho antes dos dados
    con.execute(f"""CREATE VIEW inmet_2024 AS SELECT * FROM read_csv('{(INMET_2024 / '*.CSV').as_posix()}',
        skip=9, header=false, delim=';', decimal_separator=',', encoding='latin-1',
        names={COLUNAS_INMET}, filename=true)""")
    con.execute(f"CREATE VIEW municipios AS SELECT * FROM read_csv('{MUNICIPIOS.as_posix()}', header=true)")
    return con


def _coordenadas_inmet_2024():
    """Lê o código, a latitude e a longitude que ficam no cabeçalho de cada CSV do INMET 2024."""
    estacoes = []
    for arquivo in sorted(INMET_2024.glob('*.CSV')):
        with open(arquivo, encoding='latin-1') as f:
            cabecalho = dict(linha.strip().split(':;') for linha in [next(f) for _ in range(8)])
        estacoes.append((cabecalho['CODIGO (WMO)'],
                         float(cabecalho['LATITUDE'].replace(',', '.')),
                         float(cabecalho['LONGITUDE'].replace(',', '.'))))
    return estacoes


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
    ROW_NUMBER() OVER janela AS dia_da_serie  -- 1 no primeiro dia, 2 no segundo... (usado no passo 11)
FROM grade
WINDOW janela AS (PARTITION BY id_municipio ORDER BY dia)
""")


def ler_clima_horario(con):
    """Passo 4: junta as medições de hora em hora do INMET 2024 e do BDMEP 2025."""
    return _rodar(con, """
-- Cria a tabela clima_horario: uma linha por estação e hora, de 2024 até o último dia da grade.
CREATE OR REPLACE TABLE clima_horario AS
SELECT
    split_part(parse_filename(filename), '_', 4) AS id_estacao,
                                              -- o código da estação está no nome do arquivo
    CAST(data AS DATE) AS dia,
    NULLIF(chuva, -9999) AS chuva,            -- o INMET usa -9999 para "sem medição"
    NULLIF(temp_max, -9999) AS temp_max,
    NULLIF(umidade_min, -9999) AS umidade_min,
    NULLIF(vento, -9999) AS vento
FROM inmet_2024
UNION ALL                                     -- empilha embaixo as linhas de 2025
SELECT id_estacao, CAST(data AS DATE), precipitacao_total, temperatura_max, umidade_rel_min, vento_velocidade
FROM (SELECT DISTINCT * FROM bdmep)           -- o BDMEP vem com as linhas em dobro: fica uma de cada
WHERE data <= (SELECT MAX(dia) FROM grade)
""")


def agregar_clima_diario(con):
    """Passo 5: transforma as medições de hora em hora em um valor por estação e dia."""
    return _rodar(con, f"""
-- Um valor diário só vale se a estação mediu pelo menos {HORAS_MINIMAS} das 24 horas.
CREATE OR REPLACE TABLE clima_diario AS
SELECT
    id_estacao,
    dia,
    CASE WHEN COUNT(umidade_min) >= {HORAS_MINIMAS} THEN MIN(umidade_min) END AS umidade_min,
                                              -- a umidade mais baixa do dia (%)
    CASE WHEN COUNT(temp_max) >= {HORAS_MINIMAS} THEN MAX(temp_max) END AS temp_max,
                                              -- a temperatura mais alta do dia (°C)
    CASE WHEN COUNT(chuva) >= {HORAS_MINIMAS} THEN CAST(SUM(CAST(chuva AS DECIMAL(9, 2))) AS DOUBLE) END AS chuva,
                                              -- a chuva somada do dia (mm); somar em DECIMAL é exato
                                              -- e dá sempre o mesmo resultado, em qualquer ordem
    CASE WHEN COUNT(vento) >= {HORAS_MINIMAS} THEN CAST(ROUND(AVG(CAST(vento AS DECIMAL(9, 2))), 2) AS DOUBLE) END AS vento
                                              -- a velocidade média do vento no dia (m/s)
FROM clima_horario
GROUP BY id_estacao, dia
""")


def ligar_estacoes_proximas(con):
    """Passo 6: liga cada município às estações mais próximas da sua sede."""
    con.execute('CREATE OR REPLACE TABLE coordenadas_2024 (id_estacao VARCHAR, latitude DOUBLE, longitude DOUBLE)')
    con.executemany('INSERT INTO coordenadas_2024 VALUES (?, ?, ?)', _coordenadas_inmet_2024())
    return _rodar(con, f"""
-- Coordenadas das estações: do cabeçalho dos arquivos de 2024 e, para as que faltarem, do cadastro do BDMEP.
CREATE OR REPLACE TABLE coordenadas AS
SELECT id_estacao, latitude, longitude FROM coordenadas_2024
UNION
SELECT id_estacao, latitude, longitude FROM estacoes
WHERE id_estacao NOT IN (SELECT id_estacao FROM coordenadas_2024);

-- Distância em km entre a sede de cada município e cada estação (fórmula de Haversine,
-- que mede a distância sobre a superfície da Terra). Ficam as {ESTACOES_POR_MUNICIPIO} mais próximas, a até {DISTANCIA_MAXIMA_KM} km.
CREATE OR REPLACE TABLE estacoes_proximas AS
WITH distancias AS (
    SELECT
        m.codigo_ibge AS id_municipio,
        c.id_estacao,
        2 * 6371 * ASIN(SQRT(
            POWER(SIN(RADIANS(c.latitude - m.latitude) / 2), 2)
            + COS(RADIANS(m.latitude)) * COS(RADIANS(c.latitude))
              * POWER(SIN(RADIANS(c.longitude - m.longitude) / 2), 2))) AS distancia_km
    FROM municipios m
    CROSS JOIN coordenadas c                  -- cada município com cada estação
)
SELECT *
FROM distancias
WHERE distancia_km <= {DISTANCIA_MAXIMA_KM}
-- ROW_NUMBER numera as estações da mais próxima à mais distante, e QUALIFY fica só com as primeiras.
QUALIFY ROW_NUMBER() OVER (PARTITION BY id_municipio ORDER BY distancia_km, id_estacao) <= {ESTACOES_POR_MUNICIPIO}
""")


def criar_clima_vespera(con):
    """Passo 7: o clima da véspera (e da última semana), vindo da estação mais próxima que mediu."""
    return _rodar(con, """
-- Para cada município e dia, cada medida vem da estação mais próxima que mediu aquilo naquele dia.
-- ARG_MIN(valor, distância) devolve o valor da menor distância; FILTER ignora as estações sem medição.
CREATE OR REPLACE TABLE clima_municipio AS
SELECT
    p.id_municipio,
    c.dia,
    MIN(p.distancia_km) AS distancia_estacao_km,  -- a distância da estação mais próxima que mediu algo no dia
    ARG_MIN(c.umidade_min, (p.distancia_km, p.id_estacao)) FILTER (WHERE c.umidade_min IS NOT NULL) AS umidade_min,
    ARG_MIN(c.temp_max, (p.distancia_km, p.id_estacao)) FILTER (WHERE c.temp_max IS NOT NULL) AS temp_max,
    ARG_MIN(c.chuva, (p.distancia_km, p.id_estacao)) FILTER (WHERE c.chuva IS NOT NULL) AS chuva,
    ARG_MIN(c.vento, (p.distancia_km, p.id_estacao)) FILTER (WHERE c.vento IS NOT NULL) AS vento
FROM estacoes_proximas p
JOIN clima_diario c ON c.id_estacao = p.id_estacao
WHERE c.umidade_min IS NOT NULL OR c.temp_max IS NOT NULL OR c.chuva IS NOT NULL OR c.vento IS NOT NULL
GROUP BY p.id_municipio, c.dia;

-- Traz esse clima para a grade.
CREATE OR REPLACE TABLE grade AS
SELECT g.*, c.distancia_estacao_km, c.umidade_min, c.temp_max, c.chuva, c.vento
FROM grade g
LEFT JOIN clima_municipio c
    ON c.id_municipio = g.id_municipio AND c.dia = g.dia;

-- Depois, desloca tudo um dia para trás: o modelo só pode ver o clima de ATÉ ONTEM.
-- O clima do próprio dia sai da tabela no fim.
CREATE OR REPLACE TABLE grade AS
SELECT
    * EXCLUDE (distancia_estacao_km, umidade_min, temp_max, chuva, vento),
    LAG(distancia_estacao_km, 1) OVER janela AS distancia_estacao_km,
    LAG(umidade_min, 1) OVER janela AS umidade_min_ontem,
    LAG(temp_max, 1) OVER janela AS temp_max_ontem,
    LAG(chuva, 1) OVER janela AS chuva_ontem,
    LAG(vento, 1) OVER janela AS vento_ontem,
    CAST(SUM(CAST(chuva AS DECIMAL(9, 2))) OVER (janela ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS DOUBLE) AS chuva_7d
                                              -- chuva somada nos 7 dias anteriores (sem hoje)
FROM grade
WINDOW janela AS (PARTITION BY id_municipio ORDER BY dia)
""")


def criar_calendario(con):
    """Passo 8: o mês e o dia do ano, porque o fogo muda com a época do ano."""
    return _rodar(con, """
CREATE OR REPLACE TABLE grade AS
SELECT
    *,
    MONTH(dia) AS mes,                        -- 1 a 12
    DAYOFYEAR(dia) AS dia_do_ano              -- 1 a 366
FROM grade
""")


def criar_uso_do_solo(con):
    """Passo 9: o uso do solo de cada município (MapBiomas 2021) e a perda de vegetação nativa."""
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
    """Passo 10: o nível de risco do dia, a partir do número de focos."""
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
    """Passo 11: tira os primeiros 30 dias, que não têm 30 dias de passado."""
    return _rodar(con, f"""
CREATE OR REPLACE TABLE grade AS
SELECT * EXCLUDE (dia_da_serie)               -- todas as colunas, menos a auxiliar do passo 3
FROM grade
WHERE dia_da_serie > {DIAS_SEM_HISTORICO}                 -- só a partir do 31º dia da série
ORDER BY id_municipio, dia
""")


def remover_sem_clima(con):
    """Passo 12: tira as linhas sem nenhuma medida de clima na véspera e registra quais saíram."""
    return _rodar(con, """
-- Guarda, por município, quantas linhas sairão, para a auditoria.
CREATE OR REPLACE TABLE linhas_sem_clima AS
SELECT
    id_municipio,
    sigla_uf,
    COUNT(*) FILTER (WHERE sem_clima) AS linhas_retiradas,
    COUNT(*) AS linhas_na_grade,
    SUM(focos) FILTER (WHERE sem_clima) AS focos_retirados
FROM (SELECT *, umidade_min_ontem IS NULL AND temp_max_ontem IS NULL AND chuva_ontem IS NULL
                AND vento_ontem IS NULL AS sem_clima FROM grade)
GROUP BY id_municipio, sigla_uf
-- HAVING filtra depois de agrupar: fica só o município que perdeu alguma linha.
HAVING COUNT(*) FILTER (WHERE sem_clima) > 0
ORDER BY id_municipio;

-- Fica só o município-dia com pelo menos uma medida de clima na véspera.
CREATE OR REPLACE TABLE grade AS
SELECT *
FROM grade
WHERE umidade_min_ontem IS NOT NULL OR temp_max_ontem IS NOT NULL
   OR chuva_ontem IS NOT NULL OR vento_ontem IS NOT NULL
ORDER BY id_municipio, dia
""")


PASSOS = [contar_focos, montar_grade, criar_historico,
          ler_clima_horario, agregar_clima_diario, ligar_estacoes_proximas, criar_clima_vespera,
          criar_calendario, criar_uso_do_solo, criar_alvo, remover_sem_historico, remover_sem_clima]


def preparar(con):
    for passo in PASSOS:
        passo(con)
    return con


def salvar(con, caminho=ARQUIVO_PROCESSADO):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY grade TO '{caminho.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
    con.execute(f"COPY linhas_sem_clima TO '{ARQUIVO_SEM_CLIMA.as_posix()}' (HEADER, DELIMITER ',')")
    return caminho


if __name__ == '__main__':
    con = preparar(conectar())
    destino = salvar(con)
    linhas = con.execute('SELECT count(*) FROM grade').fetchone()[0]
    colunas = len(con.execute('SELECT * FROM grade LIMIT 0').description)
    print(f'{linhas} linhas e {colunas} colunas salvas em {destino}')
