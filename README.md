# Risco de incêndio por município e dia

Projeto final do MBA em Ciência de Dados da TripleTen, com a base de dados sugerida pelo curso.

| Etapa | Notebook | Código | Resultados |
|---|---|---|---|
| 1. Diagnóstico e preparação | [`01_eda.ipynb`](01_eda.ipynb) | [`src/consolidar_base.py`](src/consolidar_base.py) | [`dados/processado/`](dados/processado/) |
| 2. Modelagem e inteligência de negócio | [`02_modelagem.ipynb`](02_modelagem.ipynb) | [`src/preparar_modelagem.py`](src/preparar_modelagem.py) | [`resultados/etapa2/`](resultados/etapa2/) |
| 3. Otimização e IA responsável | [`03_otimizacao_ia_responsavel.ipynb`](03_otimizacao_ia_responsavel.ipynb) | [`src/preparar_modelagem.py`](src/preparar_modelagem.py) e [`src/criar_bioma_municipio.py`](src/criar_bioma_municipio.py) | [`resultados/etapa3/`](resultados/etapa3/) |

A resposta final do projeto está em [Conclusão do projeto](#conclusão-do-projeto), e a lista do que o enunciado pede, com o lugar de cada item, em [Onde está cada entrega](#onde-está-cada-entrega).

## O problema

Brigadas e defesa civil precisam decidir, todo dia, onde deixar equipes de prontidão. O modelo deste projeto prevê o **nível de risco de incêndio (Baixo, Médio ou Alto) para cada município e dia**, usando só o que se sabe até a véspera.

- **Quem usa:** os gestores de brigadas e de defesa civil, que decidem onde posicionar equipes, e o time técnico, que mantém o modelo.
- **Variável alvo** (o que o modelo prevê): `nivel_risco`, com três níveis, definido pelo número de focos de queimada detectados no município no dia. Cada linha da base é um **município-dia**: um município num dia.

| Nível | Regra | % dos município-dias |
|---|---|---|
| Baixo | nenhum foco | 85,83% |
| Médio | 1 a 3 focos | 7,89% |
| Alto | 4 ou mais focos | 6,29% |

## Como vamos medir o sucesso (KPIs)

A régua é uma **referência estatística mínima**, chamada persistência: prever que **o risco de hoje é o mesmo de ontem**. Ela não descreve como uma brigada trabalha. Na prática, as equipes costumam usar a previsão diária de risco de fogo do INPE, a previsão do tempo e o conhecimento do território. A persistência serve como piso: um modelo que não supere nem ela não tem valor. O modelo é comparado com ela em dias que ele não viu durante o treino.

A régua ideal seria a própria previsão de risco do INPE. Mas, na base fornecida, o risco do INPE só aparece nos dias em que já houve fogo (o viés de sobrevivência descrito abaixo), então essa comparação não é possível aqui.

| O que queremos saber | Persistência (referência mínima) | Meta do modelo |
|---|---|---|
| **Avisos a tempo:** dos dias de risco Alto, quantos são avisados com antecedência? *(recall do Alto)* | 56 de cada 100 | **pelo menos 60 de cada 100** |
| **Avisos certos:** dos avisos de risco Alto, quantos se confirmam? *(precisão do Alto)* | 56 de cada 100 | **pelo menos 55 de cada 100** |
| **Acerto geral:** nota de 0 a 1 que pesa igualmente os acertos de Baixo, Médio e Alto *(F1 macro)* | 0,57 | acompanhada; **não cair abaixo de 0,55** |
| **Custo:** gasto com equipes nos dias avisados + prejuízo dos dias de risco Alto sem equipe | calculado na Etapa 2 | menor que o da persistência, em reais |

As metas são números fixos, decididos antes da modelagem da Etapa 2. Um teste rápido, fora da entrega, serviu só para não prometer um número impossível, e depois disso elas não mudaram. As principais são sobre o risco **Alto**, que é o que pede equipe de prontidão.

**Por que não medir só "quantos dias acertou"?** Porque 85,83% dos dias são Baixo. Um modelo que dissesse "Baixo" todo dia acertaria 85,83% e nunca avisaria um incêndio.

**Por que o acerto geral é só acompanhado?** Ele inclui o nível Médio (1 a 3 focos), e o fogo isolado é o mais difícil de prever: a própria persistência acerta pouco ali (nota 0,22). Exigir que o modelo supere a persistência também no Médio poderia empurrar a escolha para um modelo pior no que importa, os dias Alto.

Os termos entre parênteses são os nomes técnicos das medidas, usados no notebook.

## O ponto de partida: o dado que falta

A base de queimadas só registra onde o satélite viu fogo. É o mesmo **viés de sobrevivência** do estudo de Abraham Wald sobre os aviões da Segunda Guerra: os dados que faltam são os que mais importam. Por exemplo, 67,01% dos focos estão na faixa de risco crítico do INPE, porque o risco só é registrado onde já está queimando.

Por isso, a base do modelo é uma **grade com os municípios em todos os dias**, em que o dia sem foco vale zero.

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

A consolidação é feita em SQL por [`src/consolidar_base.py`](src/consolidar_base.py), com cada consulta comentada linha por linha em português. O notebook mostra cada passo com a consulta, um resumo dos comandos de SQL usados e o resultado num município de exemplo (Altamira, PA). O SQL roda no DuckDB, que lê os CSVs grandes direto do disco, sem precisar de um banco de dados instalado. Os 12 passos são:

1. **Contar os focos** de satélites de órbita polar por município e dia, sem duplicados. Os geoestacionários contam o mesmo fogo várias vezes ao dia.
2. **Montar a grade** com todos os municípios em todos os dias, com zero no dia sem foco.
3. **Criar o histórico** de focos (ontem, últimos 7 e 30 dias), sempre sem o próprio dia.
4. **Juntar o clima de hora em hora** do INMET 2024 e do BDMEP 2025, tratando o `-9999` como vazio e tirando as linhas em dobro do BDMEP.
5. **Fazer um valor por estação e dia** (umidade mínima, temperatura máxima, chuva e vento), só quando a estação mediu pelo menos 18 das 24 horas.
6. **Ligar cada município às 10 estações mais próximas** da sua sede, a até 400 km.
7. **Criar o clima da véspera:** cada medida vem da estação mais próxima que mediu naquele dia. Entram o clima de ontem, a chuva dos últimos 7 dias e a distância da estação usada, sempre sem o próprio dia.
8. **Criar o calendário:** mês e dia do ano.
9. **Acrescentar o uso do solo** do MapBiomas (2021) e a perda de vegetação nativa de 2016 a 2021.
10. **Criar o alvo:** Baixo, Médio ou Alto, pelo número de focos.
11. **Retirar os primeiros 30 dias,** que não têm 30 dias de passado para calcular o histórico.
12. **Retirar as linhas sem nenhum clima na véspera:** 3 103 linhas (0,15%) e 0,11% dos focos, listadas por município em [`dados/processado/linhas_sem_clima_por_municipio.csv`](dados/processado/linhas_sem_clima_por_municipio.csv).

O resultado é [`dados/processado/grade_municipio_dia.parquet`](dados/processado/), com 2 106 411 linhas, 5 562 municípios, 379 dias e 26 colunas. Parquet é um formato de arquivo compacto para tabelas grandes: a base inteira ocupa 9 MB.

### O que a análise encontrou

**Sobre os dados**

- **As bases fornecidas quase não se encontram no tempo.** Queimadas e BDMEP coexistem por só 43 dias (jan e fev de 2025), e o uso do solo termina em 2021. O clima de 2024 foi completado com os dados históricos do INMET.
- **O BDMEP vem em dobro.** Quase toda medição aparece duas vezes, idêntica (4 891 176 linhas para 2 452 104 combinações de estação, dia e hora). A análise usa só as linhas distintas.
- **O dicionário do MapBiomas fornecido não bate com os dados.** O arquivo usa os 28 códigos da legenda oficial da Coleção 7 (que cobre 1985 a 2021), agrupados em 7 grupos de uso do solo.
- **Clima com vazios.** Falha de sensor é comum, e a rede de estações é rala na Amazônia. Por isso, cada medida vem da estação mais próxima que mediu naquele dia. Metade dos municípios tem estação a até 33,8 km, e 1,55% dos município-dias usam clima de mais de 150 km. O limite de 400 km foi escolhido pela perda: com 150 km, as linhas sem clima levariam 14% dos focos do país; com 400 km, 0,11%. Os poucos vazios restantes (0,13% ou menos em cada coluna) são preenchidos dentro do treino, na Etapa 2.
- **Algumas colunas não entram como feature** (as colunas que o modelo usa para prever), porque só existem (ou só são conhecidas) quando já há fogo: `risco_fogo`, `dias_sem_chuva`, `precipitacao` e o bioma.

**Sobre o risco**

- **O fogo de ontem é o melhor aviso.** Com foco ontem, a chance de foco hoje é 53,16%; sem foco ontem, 7,73%. O teste qui-quadrado, que compara a contagem de dias com o que se esperaria se o fogo de ontem não tivesse relação com o de hoje, deu p < 0,001 (a chance de uma diferença desse tamanho ser sorte é menor que 1 em 1 000).
- **O ar seco acompanha o fogo.** A umidade relativa mínima média da véspera foi de 35,82% antes dos dias com foco, contra 47,72% antes dos dias sem foco (teste t de Welch, que compara médias entre dois grupos, p < 0,001). A diferença se mantém dentro do mesmo município: em 99,0% dos 4 557 municípios com dias suficientes, a véspera do fogo é mais seca.
- **Há estação do fogo e geografia do fogo.** Em setembro, 15,38% dos município-dias são Alto. Os municípios mais florestados e os que mais perderam vegetação nativa têm mais dias de risco Alto.

## Etapa 2: modelagem e inteligência de negócio ([`02_modelagem.ipynb`](02_modelagem.ipynb))

**Três modelos:** regressão logística (dá um peso a cada coluna e soma), floresta aleatória (centenas de árvores de decisão que votam) e LightGBM (árvores em sequência, cada uma corrigindo os erros da anterior). A preparação comum (colunas, períodos, régua e métricas) fica em [`src/preparar_modelagem.py`](src/preparar_modelagem.py).

**Divisão por tempo:** o modelo aprende até setembro de 2024 (treino), as notas de corte são escolhidas em outubro (validação) e a nota final sai de novembro de 2024 a fevereiro de 2025 (teste). O teste cai na época de chuva, com menos dias Alto, e por isso a própria persistência vai pior ali do que na base inteira.

**Resultado no teste:**

| | Persistência | Regressão logística (escolhida) | Meta |
|---|---|---|---|
| Dias Alto avisados (recall do Alto) | 49,8 de cada 100 | 49,9 de cada 100 | 60: **não atingida** |
| Avisos certos (precisão do Alto) | 49,2 de cada 100 | 58,7 de cada 100 | 55: **atingida** |
| Acerto geral (F1 macro) | 0,5490 | 0,5649 | 0,55: **atingida** |
| Custo no período de teste | R$ 434,8 milhões | R$ 429,2 milhões | menor: **atingida** |

- **Os três modelos superam a persistência** no acerto geral e no F1 do Alto. A regressão logística foi escolhida antes do teste, pelo maior acerto geral na validação. Olhando só o Alto na validação, a floresta fica logo à frente, e o LightGBM sem ajustes fica atrás.
- **O resultado se sustenta em parte:** vale em 1 112 municípios que o modelo nunca viu no treino e em 3 de 5 meses, os de mais fogo. Em janeiro e fevereiro, fica abaixo da persistência.
- **Limitação encontrada:** o ganho está nos municípios maiores, que concentram cerca de 80% dos dias Alto. Nos menores, a persistência acerta mais. A Etapa 3 trata esse ponto.
- **Em reais:** custo de equipe a partir dos salários do Prevfogo/Ibama e prejuízo por hectare a partir da estimativa da CNA. A economia contra a persistência é positiva nos 15 cenários testados. Escolhendo o corte pelo menor custo, em vez do maior acerto geral, o modelo avisa 91 de cada 100 dias Alto, o que mostra que a meta de recall é uma escolha de custo.
- **Plano de teste A/B:** sorteio de grupos de municípios vizinhos, em pares parecidos, durante uma estação seca, medindo a área queimada por foco.

Os resultados em tabela estão em [`resultados/etapa2/`](resultados/etapa2/).

## Etapa 3: otimização e IA responsável ([`03_otimizacao_ia_responsavel.ipynb`](03_otimizacao_ia_responsavel.ipynb))

- **Otimização com o Optuna** (ferramenta que testa combinações de ajustes do modelo): 30 tentativas subiram o acerto geral do LightGBM na validação de 0,5762 para 0,5874, acima dos 0,5794 da regressão logística. Por isso, o LightGBM otimizado é o modelo final.
- **Um corte do Alto por tamanho de município:** o modelo passa a superar a persistência nas 3 faixas maiores e fica quase igual na menor, mas ainda perde na faixa 2. Na validação, o corte único tinha acerto geral maior; o corte por faixa foi uma escolha declarada, para não abandonar os municípios pequenos.
- **As 3 colunas que mais pesam, pelo SHAP** (método que mostra quanto cada coluna pesou em cada previsão): focos nos últimos 30 dias (23,7%), umidade mínima de ontem (9,0%) e chuva nos últimos 7 dias (8,9%).
- **Viés:** o modelo avisa 73 de cada 100 dias Alto no Norte, mas só 6 no Sudeste, no período de teste. A causa provável é a estação: em outubro, o Sudeste sobe para 49. O Sul fica baixo nos dois períodos. O notebook traz o que fazer com isso.
- **Boletim em texto com regra fixa:** frase padrão com o nível previsto e os 3 fatores do SHAP, sem modelo de linguagem (LLM). Assim, nada é inventado, não há chave de serviço pago num repositório público e o resultado é reproduzível.
- **Modelo final guardado:** `resultados/etapa3/modelo_final.txt`, com as regras de decisão em `cortes_finais.json`.

## Conclusão do projeto

**Hipótese:** com o que se sabe até a véspera, um modelo avisa os dias de risco Alto melhor do que a regra "hoje = ontem" e reduz o custo de posicionar equipes.

**Resposta: confirmada em parte.** O modelo final é melhor que a régua e custa menos, mas não atinge a meta de dias Alto avisados.

| Meta (período de teste) | Persistência | Modelo final | Atingida? |
|---|---|---|---|
| Acerto geral (F1 macro) de pelo menos 0,55 | 0,5490 | 0,5677 | **sim** |
| Pelo menos 55 de cada 100 avisos Alto certos | 49,2 | 56,8 | **sim** |
| Pelo menos 60 de cada 100 dias Alto avisados | 49,8 | 51,8 | **não** |
| Custo menor que o da persistência | R$ 434,8 milhões | R$ 415,8 milhões | **sim** |

O resultado depende da estação. Em novembro, mês do teste com mais fogo, o modelo atinge as duas metas do Alto (60,3 dias avisados e 62,2 avisos certos, de cada 100). Em janeiro e fevereiro, com poucos dias Alto, ele fica bem abaixo. A economia é uma estimativa, que depende da premissa dos 5 hectares; a comprovação viria do teste A/B planejado.

## Onde está cada entrega

| O que o enunciado pede | Onde está |
|---|---|
| Alvo, KPIs e README | início deste README |
| Script de consolidação | [`src/consolidar_base.py`](src/consolidar_base.py) |
| EDA, teste de hipótese e base pronta | [`01_eda.ipynb`](01_eda.ipynb) e [`dados/processado/`](dados/processado/) |
| Dicionário de dados | [`dicionario_dados.txt`](dicionario_dados.txt) |
| Três modelos e suas métricas | [`02_modelagem.ipynb`](02_modelagem.ipynb), seções 3 a 5 |
| Impacto em reais | [`02_modelagem.ipynb`](02_modelagem.ipynb), seção 7 |
| Plano de teste A/B | [`02_modelagem.ipynb`](02_modelagem.ipynb), seção 8 |
| Otimização com Optuna | [`03_otimizacao_ia_responsavel.ipynb`](03_otimizacao_ia_responsavel.ipynb), seção 1 |
| Explicabilidade com SHAP | [`03_otimizacao_ia_responsavel.ipynb`](03_otimizacao_ia_responsavel.ipynb), seção 4 |
| Testes de viés | [`03_otimizacao_ia_responsavel.ipynb`](03_otimizacao_ia_responsavel.ipynb), seção 5 |
| Texto automático (opcional) | [`03_otimizacao_ia_responsavel.ipynb`](03_otimizacao_ia_responsavel.ipynb), seção 6, com regra fixa, sem LLM |
| Etapa 4, deploy (opcional) | não feita |
| Relatórios de avaliação | [`Relatorios/`](Relatorios/) |

## Como rodar

Requer Python 3.12.

```bash
python -m venv .venv
.venv\Scripts\activate        # no Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python src/consolidar_base.py # gera dados/processado/grade_municipio_dia.parquet
jupyter nbconvert --to notebook --execute --inplace 01_eda.ipynb
python src/criar_bioma_municipio.py # gera dados/processado/bioma_municipio.csv
jupyter nbconvert --to notebook --execute --inplace 02_modelagem.ipynb
jupyter nbconvert --to notebook --execute --inplace 03_otimizacao_ia_responsavel.ipynb
```

O `consolidar_base.py`, o `01_eda.ipynb` e o `criar_bioma_municipio.py` precisam dos arquivos brutos. Os notebooks 02 e 03 só precisam dos arquivos processados, que já estão no repositório, e levam cerca de 8 e 15 minutos.

## Estrutura

```
├── 01_eda.ipynb                Etapa 1: consolidação passo a passo e análise exploratória
├── 02_modelagem.ipynb          Etapa 2: modelos, notas de corte, robustez, custo em reais e plano A/B
├── 03_otimizacao_ia_responsavel.ipynb   Etapa 3: Optuna, corte por tamanho, SHAP, viés, boletim e conclusão
├── src/consolidar_base.py      script de consolidação (SQL no DuckDB)
├── src/criar_bioma_municipio.py   bioma de cada município, usado só no teste de viés
├── src/preparar_modelagem.py   colunas, divisão por tempo, régua e métricas usadas nas Etapas 2 e 3
├── resultados/                 tabelas das Etapas 2 e 3 (CSV) e modelo final (etapa3/)
├── dados/
│   ├── brutos/                 CSVs fornecidos pela TripleTen e inmet_2024/ (fora do Git)
│   ├── externos/               coordenadas das sedes dos municípios (fonte no LEIA-ME)
│   └── processado/             grade município × dia, bioma por município e linhas retiradas por falta de clima
├── dicionario_dados.txt
├── requirements.txt
└── Relatorios/                 relatórios de aprovação da TripleTen
```

## Limitações conhecidas

- "Nenhum foco detectado" não é o mesmo que "nenhum fogo": nuvens e fogos pequenos escapam do satélite. O alvo mede o fogo visível por satélite.
- O uso do solo é de 2021, três anos antes das queimadas.
- O clima vem da estação mais próxima da sede que mediu no dia, a até 400 km. Em município grande ou longe de estação, ele descreve o município só de forma aproximada; 1,55% dos município-dias usam clima de mais de 150 km.
- Saíram da base 3 103 linhas sem nenhum clima, incluindo 4 municípios inteiros, todos no Amazonas.
- Três municípios com focos (1 130 focos) não existem na base do MapBiomas e ficaram fora da grade.
- O modelo avisa muito menos dias Alto no Sudeste e no Sul do que no Norte e no Nordeste, e vai pior que a persistência no Sudeste, no Sul, na Mata Atlântica e no Pampa no período de teste.
- Há só um ano de dados, com uma única estação seca no treino e nenhum dia de outubro a dezembro, meses que o modelo vê pela primeira vez na validação e no teste.
- A área a mais que queima num dia Alto sem equipe (5 hectares) não tem fonte publicada; por isso a conta em reais vem com uma tabela de cenários.
- As datas dos focos e as horas do INMET estão no horário de Greenwich (UTC/GMT). Um foco detectado depois das 21h no horário de Brasília conta para o dia seguinte.
