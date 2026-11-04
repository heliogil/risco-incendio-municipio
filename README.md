# Risco de incêndio por município e dia

Projeto final do MBA em Ciência de Dados da TripleTen, com a base sugerida pelo curso (Caminho 1).

## O problema

Brigadas e defesa civil precisam decidir, todo dia, onde deixar equipes de prontidão. O modelo deste projeto prevê o **nível de risco de incêndio (Baixo, Médio ou Alto) para cada município e dia**, usando só o que se sabe até a véspera.

- **Quem usa:** os gestores de brigadas e de defesa civil, que decidem onde posicionar equipes, e o time técnico, que mantém o modelo.
- **Variável alvo:** `nivel_risco`, com três classes, definida pelo número de focos de queimada detectados no município no dia.

| Nível | Regra | % dos município-dias |
|---|---|---|
| Baixo | nenhum foco | 85,81% |
| Médio | 1 a 3 focos | 7,89% |
| Alto | 4 ou mais focos | 6,30% |

## KPIs

| Tipo | Meta | Referência: regra "o risco de hoje é o de ontem" |
|---|---|---|
| Técnico | F1 macro acima da regra de referência, no conjunto de teste | F1 macro 0,5670 |
| Técnico | Recall da classe Alto acima da regra de referência | recall Alto 0,5569 |
| Negócio | Antecipar mais dias de risco Alto com menos equipes de prontidão desperdiçadas | precisão Alto 0,5566 |

O F1 macro dá o mesmo peso às três classes. Assim, o modelo não pode "ganhar" só acertando os dias Baixo.

## O ponto de partida: o dado que falta

A base de queimadas só registra onde o satélite viu fogo. É o mesmo **viés de sobrevivência** do estudo de Abraham Wald sobre os aviões da Segunda Guerra: os dados que faltam são os que mais importam. Por exemplo, 67,01% dos focos estão na faixa de risco crítico do INPE, porque o risco só é registrado onde já está queimando.

Por isso, a base do modelo é uma **grade com todos os 5 566 municípios em todos os dias**, em que o dia sem foco vale zero.

## Os dados

Bases da [Base dos Dados](https://basedosdados.org/), fornecidas pela TripleTen:

- **Queimadas (INPE):** 8 226 944 focos, de 01/01/2024 a 12/02/2025.
- **MapBiomas:** área de cada classe de uso do solo por município, de 1985 a 2021.
- **BDMEP (INMET):** medições horárias de 567 estações, de 01/01 a 30/06/2025.
- **Estações do BDMEP:** cadastro de 612 estações.

Os arquivos brutos (cerca de 1,5 GB) não estão no repositório. Para rodar, copie os quatro CSVs fornecidos pela TripleTen para `dados/brutos/`.

O dicionário completo está em [`dicionario_dados.txt`](dicionario_dados.txt).

## Etapa 1: diagnóstico e preparação ([`01_eda.ipynb`](01_eda.ipynb))

A consolidação é feita em SQL (DuckDB) por [`src/consolidar_base.py`](src/consolidar_base.py) e mostrada passo a passo no notebook:

1. Conta os focos de satélites de órbita polar por município e dia, sem duplicados. Os geoestacionários contam o mesmo fogo várias vezes ao dia.
2. Monta a grade município × dia, com zero no dia sem foco.
3. Cria o histórico de focos (ontem, 7 e 30 dias), sempre sem o próprio dia.
4. Acrescenta o calendário e o uso do solo do MapBiomas (2021) e a perda de vegetação nativa de 2016 a 2021.
5. Cria o alvo e retira os primeiros 30 dias, que não têm histórico.

O resultado é [`dados/processado/grade_municipio_dia.parquet`](dados/processado/), com 2 109 514 linhas e 20 colunas.

### O que a análise encontrou

**Sobre os dados**

- **As bases quase não se encontram no tempo.** Queimadas e clima coexistem por só 43 dias (jan e fev de 2025), e o uso do solo termina em 2021. O clima ficou fora das features e foi usado num teste de hipótese.
- **O dicionário do MapBiomas fornecido não bate com os dados.** O arquivo usa os 28 códigos da legenda oficial da Coleção 8, que foram agrupados em 7 grupos de uso do solo.
- **Algumas colunas não entram como feature,** porque só existem (ou só são conhecidas) quando já há fogo: `risco_fogo`, `dias_sem_chuva`, `precipitacao` e o bioma.

**Sobre o risco**

- **O fogo de ontem é o melhor aviso.** Com foco ontem, a chance de foco hoje é 53,17%; sem foco ontem, 7,74%. O teste qui-quadrado deu p < 0,001.
- **O ar seco acompanha o fogo.** A umidade relativa mínima média foi de 43,05% nos dias com foco, contra 52,00% nos dias sem foco. O teste t de Welch, feito no período comum com o BDMEP, deu p < 0,001.
- **Há estação do fogo e geografia do fogo.** Em setembro, 15,42% dos município-dias são Alto. Os municípios mais florestados e os que mais perderam vegetação nativa têm mais dias de risco Alto.

## Próximas etapas

- **Etapa 2: modelagem e inteligência de negócio.** Três modelos (regressão logística, floresta aleatória e LightGBM) com divisão de treino e teste por tempo, métricas de classificação, conversão do resultado em reais (custo de prontidão contra custo de incêndio) e plano de teste A/B.
- **Etapa 3: otimização e IA responsável.** Ajuste de hiperparâmetros com Optuna, explicabilidade com SHAP, teste de viés por região e texto automático gerado por uma LLM.

## Como rodar

Requer Python 3.12.

```bash
python -m venv .venv
.venv\Scripts\activate        # no Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python src/consolidar_base.py # gera dados/processado/grade_municipio_dia.parquet
jupyter nbconvert --to notebook --execute --inplace 01_eda.ipynb
```

## Estrutura

```
├── 01_eda.ipynb                Etapa 1: consolidação passo a passo e análise exploratória
├── src/consolidar_base.py      script de consolidação (SQL no DuckDB)
├── dados/
│   ├── brutos/                 CSVs fornecidos pela TripleTen (fora do Git)
│   └── processado/             grade município × dia, pronta para os modelos
├── dicionario_dados.txt
├── requirements.txt
└── Relatorios/                 relatórios de aprovação da TripleTen
```

## Limitações conhecidas

- "Nenhum foco detectado" não é o mesmo que "nenhum fogo": nuvens e fogos pequenos escapam do satélite. O alvo mede o fogo visível por satélite.
- O uso do solo é de 2021, três anos antes das queimadas.
- O clima do BDMEP fornecido não cobre 2024. Completar a série com os dados históricos do INMET é a principal melhoria para uma próxima versão.
- Três municípios com focos (1 130 focos) não existem na base do MapBiomas e ficaram fora da grade.
