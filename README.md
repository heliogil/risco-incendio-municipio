# Risco de incêndio por município e dia

Projeto final do MBA em Ciência de Dados da TripleTen, com a base sugerida pelo curso (Caminho 1).

## O problema

Brigadas e defesa civil precisam decidir, todo dia, onde deixar equipes de prontidão. O modelo deste projeto prevê o **nível de risco de incêndio (Baixo, Médio ou Alto) para cada município e dia**, usando só o que se sabe até a véspera.

- **Quem usa:** os gestores de brigadas e de defesa civil, que decidem onde posicionar equipes, e o time técnico, que mantém o modelo.
- **Variável alvo** (o que o modelo prevê): `nivel_risco`, com três níveis, definido pelo número de focos de queimada detectados no município no dia. Cada linha da base é um **município-dia**: um município num dia.

| Nível | Regra | % dos município-dias |
|---|---|---|
| Baixo | nenhum foco | 85,81% |
| Médio | 1 a 3 focos | 7,89% |
| Alto | 4 ou mais focos | 6,30% |

## Como vamos medir o sucesso (KPIs)

A régua é uma **referência estatística mínima**, chamada persistência: prever que **o risco de hoje é o mesmo de ontem**. Ela não descreve como uma brigada trabalha. Na prática, as equipes costumam usar a previsão diária de risco de fogo do INPE, a previsão do tempo e o conhecimento do território. A persistência serve como piso: um modelo que não supere nem ela não tem valor. O modelo é comparado com ela em dias que ele não viu durante o treino.

A régua ideal seria a própria previsão de risco do INPE. Mas, na base fornecida, o risco do INPE só aparece nos dias em que já houve fogo (o viés de sobrevivência descrito abaixo), então essa comparação não é possível aqui.

| O que queremos saber | Persistência (referência mínima) | Meta do modelo |
|---|---|---|
| **Avisos a tempo:** dos dias de risco Alto, quantos são avisados com antecedência? *(recall do Alto)* | 56 de cada 100 | **pelo menos 60 de cada 100** |
| **Avisos certos:** dos avisos de risco Alto, quantos se confirmam? *(precisão do Alto)* | 56 de cada 100 | **pelo menos 55 de cada 100** |
| **Acerto geral:** nota de 0 a 1 que pesa igualmente os acertos de Baixo, Médio e Alto *(F1 macro)* | 0,57 | acompanhada; **não cair abaixo de 0,55** |
| **Custo:** gasto com equipes em dias que não pegam fogo + prejuízo dos dias de risco Alto sem equipe | calculado na Etapa 2 | menor que o da persistência, em reais |

As metas são números fixos, decididos antes de treinar qualquer modelo. As principais são sobre o risco **Alto**, que é o que pede equipe de prontidão.

**Por que não medir só "quantos dias acertou"?** Porque 85,81% dos dias são Baixo. Um modelo que dissesse "Baixo" todo dia acertaria 85,81% e nunca avisaria um incêndio.

**Por que o acerto geral é só acompanhado?** Ele inclui o nível Médio (1 a 3 focos), e o fogo isolado é o mais difícil de prever: a própria persistência acerta pouco ali (nota 0,22). Exigir que o modelo supere a persistência também no Médio poderia empurrar a escolha para um modelo pior no que importa, os dias Alto.

Os termos entre parênteses são os nomes técnicos das medidas, usados no notebook.

## O ponto de partida: o dado que falta

A base de queimadas só registra onde o satélite viu fogo. É o mesmo **viés de sobrevivência** do estudo de Abraham Wald sobre os aviões da Segunda Guerra: os dados que faltam são os que mais importam. Por exemplo, 67,01% dos focos estão na faixa de risco crítico do INPE, porque o risco só é registrado onde já está queimando.

Por isso, a base do modelo é uma **grade com todos os 5 566 municípios em todos os dias**, em que o dia sem foco vale zero.

## Os dados

Bases da [Base dos Dados](https://basedosdados.org/), fornecidas pela TripleTen:

- **Queimadas (INPE, Instituto Nacional de Pesquisas Espaciais):** 8 226 944 focos, de 01/01/2024 a 12/02/2025.
- **MapBiomas** (projeto que mapeia a cobertura do solo do Brasil por satélite): área de cada classe de uso do solo por município, de 1985 a 2021 (legenda da Coleção 7).
- **BDMEP (banco de dados do INMET, Instituto Nacional de Meteorologia):** medições horárias de 567 estações, de 01/01 a 30/06/2025.
- **Estações do BDMEP:** cadastro de 612 estações.

Complementos públicos:

- **Clima de 2024 (INMET):** o BDMEP fornecido só cobre 2025 e coexiste com as queimadas por 43 dias. O clima de 2024 veio dos [dados históricos anuais do INMET](https://portal.inmet.gov.br/dadoshistoricos), a mesma fonte do BDMEP: 565 estações automáticas, 4 962 960 medições de hora em hora.
- **Coordenadas dos municípios:** a sede de cada município, do repositório [kelvins/municipios-brasileiros](https://github.com/kelvins/municipios-brasileiros) (licença MIT), guardado em [`dados/externos/`](dados/externos/). Servem para ligar cada município à estação meteorológica mais próxima.

Os arquivos brutos (cerca de 1,9 GB) não estão no repositório, porque passam do limite de tamanho do GitHub. Para rodar:

1. Copie para `dados/brutos/` os quatro CSVs fornecidos pela TripleTen: `queimadas_2024_2025.csv`, `MapBiomas.csv`, `BDMEP-2025.csv` e `BDMEP-estacao.csv`. Os mesmos dados são públicos na [Base dos Dados](https://basedosdados.org/).
2. Baixe no [portal do INMET](https://portal.inmet.gov.br/dadoshistoricos) o arquivo do ano 2024 e extraia os 565 CSVs em `dados/brutos/inmet_2024/`.

A base já processada, que é o que os modelos usam, está no repositório.

O dicionário completo está em [`dicionario_dados.txt`](dicionario_dados.txt).

## Etapa 1: diagnóstico e preparação ([`01_eda.ipynb`](01_eda.ipynb))

A consolidação é feita em SQL por [`src/consolidar_base.py`](src/consolidar_base.py), com cada consulta comentada linha por linha em português. O notebook mostra cada passo com a consulta, um resumo dos comandos de SQL usados e o resultado num município de exemplo (Altamira, PA). O SQL roda no DuckDB, que lê os CSVs grandes direto do disco, sem precisar de um banco de dados instalado. Os passos são:

1. **Contar os focos** de satélites de órbita polar por município e dia, sem duplicados. Os geoestacionários contam o mesmo fogo várias vezes ao dia.
2. **Montar a grade** com todos os municípios em todos os dias, com zero no dia sem foco.
3. **Criar o histórico** de focos (ontem, últimos 7 e 30 dias), sempre sem o próprio dia.
4. **Juntar o clima de hora em hora** do INMET 2024 e do BDMEP 2025, tratando o `-9999` como vazio e tirando as linhas em dobro do BDMEP.
5. **Fazer um valor por estação e dia** (umidade mínima, temperatura máxima, chuva e vento), só quando a estação mediu pelo menos 18 das 24 horas.
6. **Ligar cada município à estação boa mais próxima** da sua sede (que mediu a umidade em pelo menos 80% dos dias), a até 150 km.
7. **Criar o clima da véspera:** o clima de ontem e a chuva dos últimos 7 dias, sempre sem o próprio dia.
8. **Criar o calendário:** mês e dia do ano.
9. **Acrescentar o uso do solo** do MapBiomas (2021) e a perda de vegetação nativa de 2016 a 2021.
10. **Criar o alvo:** Baixo, Médio ou Alto, pelo número de focos.
11. **Retirar os primeiros 30 dias,** que não têm 30 dias de passado para calcular o histórico.

O resultado é [`dados/processado/grade_municipio_dia.parquet`](dados/processado/), com 2 109 514 linhas e 26 colunas. Parquet é um formato de arquivo compacto para tabelas grandes: a base inteira ocupa 8 MB.

### O que a análise encontrou

**Sobre os dados**

- **As bases fornecidas quase não se encontram no tempo.** Queimadas e BDMEP coexistem por só 43 dias (jan e fev de 2025), e o uso do solo termina em 2021. O clima de 2024 foi completado com os dados históricos do INMET.
- **O BDMEP vem em dobro.** Quase toda medição aparece duas vezes, idêntica (4 891 176 linhas para 2 452 104 combinações de estação, dia e hora). A análise usa só as linhas distintas.
- **O dicionário do MapBiomas fornecido não bate com os dados.** O arquivo usa os 28 códigos da legenda oficial da Coleção 7 (que cobre 1985 a 2021), agrupados em 7 grupos de uso do solo.
- **Clima com vazios.** Falha de sensor é comum: só 328 das 565 estações mediram a umidade em pelo menos 80% dos dias. Com elas, 95,7% dos municípios têm uma estação a até 150 km, e 7,64% dos município-dias ficam sem a umidade da véspera. Os vazios ficam vazios e são preenchidos dentro do treino, na Etapa 2.
- **Algumas colunas não entram como feature** (as colunas que o modelo usa para prever), porque só existem (ou só são conhecidas) quando já há fogo: `risco_fogo`, `dias_sem_chuva`, `precipitacao` e o bioma.

**Sobre o risco**

- **O fogo de ontem é o melhor aviso.** Com foco ontem, a chance de foco hoje é 53,17%; sem foco ontem, 7,74%. O teste qui-quadrado, que compara a contagem de dias com o que se esperaria se o fogo de ontem não tivesse relação com o de hoje, deu p < 0,001 (a chance de uma diferença desse tamanho ser sorte é menor que 1 em 1 000).
- **O ar seco acompanha o fogo.** A umidade relativa mínima média da véspera foi de 35,82% antes dos dias com foco, contra 47,74% antes dos dias sem foco (teste t de Welch, que compara médias entre dois grupos, p < 0,001). A diferença se mantém dentro do mesmo município: em 99,1% dos 4 289 municípios com dias suficientes, a véspera do fogo é mais seca.
- **Há estação do fogo e geografia do fogo.** Em setembro, 15,42% dos município-dias são Alto. Os municípios mais florestados e os que mais perderam vegetação nativa têm mais dias de risco Alto.

## Próximas etapas

- **Etapa 2: modelagem e inteligência de negócio.**
  - **Três modelos:** regressão logística (dá um peso a cada coluna e soma), floresta aleatória (centenas de árvores de decisão que votam) e LightGBM (árvores em sequência, cada uma corrigindo os erros da anterior).
  - **Divisão por tempo:** o modelo aprende com os meses mais antigos (treino) e recebe a nota final nos mais recentes (teste).
  - **Conversão em reais:** custo de equipes de prontidão contra o custo de incêndios sem aviso.
  - **Plano de teste A/B:** como comparar, na prática, regiões que usam o modelo com regiões que não usam.
- **Etapa 3: otimização e IA responsável.**
  - **Optuna:** ferramenta que procura os melhores ajustes do modelo.
  - **SHAP:** método que mostra quanto cada coluna pesou em cada previsão.
  - **Teste de viés por região:** ver se o modelo erra mais em alguma parte do país.
  - **Texto automático:** um boletim curto por município, escrito por um modelo de linguagem (LLM) a partir da previsão.

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
│   ├── brutos/                 CSVs fornecidos pela TripleTen e inmet_2024/ (fora do Git)
│   ├── externos/               coordenadas das sedes dos municípios (fonte no LEIA-ME)
│   └── processado/             grade município × dia, pronta para os modelos
├── dicionario_dados.txt
├── requirements.txt
└── Relatorios/                 relatórios de aprovação da TripleTen
```

## Limitações conhecidas

- "Nenhum foco detectado" não é o mesmo que "nenhum fogo": nuvens e fogos pequenos escapam do satélite. O alvo mede o fogo visível por satélite.
- O uso do solo é de 2021, três anos antes das queimadas.
- O clima vem da estação boa mais próxima da sede, a até 150 km. Em município grande ou longe de estação, ele descreve o município só de forma aproximada; 4,33% dos município-dias ficam sem estação.
- Três municípios com focos (1 130 focos) não existem na base do MapBiomas e ficaram fora da grade.
- As datas dos focos e as horas do INMET estão no horário de Greenwich (UTC/GMT). Um foco detectado depois das 21h no horário de Brasília conta para o dia seguinte.
