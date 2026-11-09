# Resposta à 1ª revisão do projeto final

Os três pontos pedidos foram atendidos. Todas as decisões novas usam só o treino e a validação (outubro de 2024), com o
critério fixado antes de comparar; o teste (novembro de 2024 a fevereiro de 2025) só mede o resultado.

## 1. Outubro estava sendo usado para tudo

**O que mudou:** o Optuna passou a avaliar cada tentativa em três dobras cronológicas dentro do treino: aprende até
junho e é avaliado em julho, aprende até julho e é avaliado em agosto, aprende até agosto e é avaliado em setembro. A
nota é a média do F1 macro nas três. Outubro ficou só para as notas de corte e para as duas escolhas finais.

**Onde:** `03_otimizacao_ia_responsavel.ipynb`, seções 1 e 2.

**Resultado:** o ganho do Optuna ficou pequeno (F1 macro médio de 0,5713 sem ajustes para 0,5731). Em outubro, a
regressão logística da Etapa 2 (0,5822) ficou à frente do LightGBM otimizado (0,5817), e por isso ela é o modelo final.
A vantagem que o LightGBM tinha antes vinha de ajustar os hiperparâmetros no próprio outubro.

## 2. O corte por faixa de tamanho nasceu de uma tabela do teste

**O que mudou:** a análise por tamanho de município da Etapa 2 passou a ser feita na validação. Na Etapa 3, a escolha
entre corte único e corte por faixa segue o critério fixado antes: o maior F1 macro em outubro.

**Onde:** `02_modelagem.ipynb`, seção 6.3, e `03_otimizacao_ia_responsavel.ipynb`, seção 2.

**Resultado:** em outubro, o corte por faixa melhora o Alto nos municípios pequenos, mas reduz o F1 macro (0,5772
contra 0,5822). Pelo critério, ficou o corte único. A tabela do teste mostra o corte por faixa só como registro.

## 3. Variáveis de calendário com um ano só de dados

**O que mudou:** os três modelos foram treinados com e sem `mes` e `dia_do_ano` e comparados na validação, com a regra
fixada antes: sair se a perda média no F1 macro fosse menor que 0,005. Sem as duas colunas, dois modelos melhoraram e a
floresta ficou praticamente igual (regressão logística de 0,5794 para 0,5822; LightGBM de 0,5762 para 0,5820; floresta de 0,5801 para 0,5792).
As duas colunas saíram do modelo, e o boletim não cita mais a época do ano como fator.

**Onde:** `02_modelagem.ipynb`, seções 3 e 4, e `src/preparar_modelagem.py`.

## Efeito no resultado final (período de teste)

| Meta | Antes da revisão | Depois da revisão | Persistência |
|---|---|---|---|
| Acerto geral (F1 macro), meta ≥ 0,55 | 0,5677 | 0,5709 | 0,5490 |
| Avisos certos no Alto, meta ≥ 55 de 100 | 56,8 | 57,6 | 49,2 |
| Dias Alto avisados, meta ≥ 60 de 100 | 51,8 | 51,2 | 49,8 |
| Custo no período de teste | R$ 415,8 milhões | R$ 420,1 milhões | R$ 434,8 milhões |

As metas atingidas são as mesmas. A economia contra a persistência passou de R$ 19,0 milhões para R$ 14,7 milhões, e a
hipótese continua confirmada em parte. Os novos números vêm de escolhas feitas sem tocar no teste.
