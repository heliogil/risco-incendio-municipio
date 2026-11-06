"""Preparação comum às Etapas 2 e 3: base, features, divisão por tempo, régua e métricas.

As duas etapas importam este arquivo, para que usem exatamente as mesmas colunas,
os mesmos períodos e as mesmas métricas.
"""
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, f1_score, precision_score, recall_score, roc_auc_score)

from consolidar_base import ARQUIVO_PROCESSADO

NIVEIS = ['Baixo', 'Médio', 'Alto']

# Colunas que o modelo pode usar: só o que se sabe até a véspera (ver 01_eda.ipynb).
FEATURES_NUMERICAS = [
    'focos_ontem', 'focos_7d', 'focos_30d', 'dias_com_foco_30d',
    'umidade_min_ontem', 'temp_max_ontem', 'chuva_ontem', 'chuva_7d', 'vento_ontem', 'distancia_estacao_km',
    'mes', 'dia_do_ano',
    'area_km2', 'pct_floresta', 'pct_natural_nao_florestal', 'pct_pastagem', 'pct_agricultura',
    'pct_mosaico', 'pct_nao_vegetada', 'pct_agua', 'perda_nativa_5a',
]
FEATURES_CATEGORICAS = ['sigla_uf']
FEATURES = FEATURES_NUMERICAS + FEATURES_CATEGORICAS

# Colunas com cauda longa, que a regressão logística recebe em log(1 + valor).
FEATURES_CAUDA_LONGA = ['focos_ontem', 'focos_7d', 'focos_30d', 'chuva_ontem', 'chuva_7d', 'area_km2']

# Divisão por tempo: o treino inclui o pico da seca de 2024 (agosto e setembro).
FIM_TREINO = '2024-09-30'
FIM_VALIDACAO = '2024-10-31'

# Premissas da conta em reais (fontes em 02_modelagem.ipynb, seção 7).
CUSTO_EQUIPE_DIA = round((2838.00 + 4 * 2128.50) / 22 * 2)
PREJUIZO_HECTARE = 5250
HECTARES_BASE = 5

REGIOES = {
    'Norte': ['AC', 'AM', 'AP', 'PA', 'RO', 'RR', 'TO'],
    'Nordeste': ['AL', 'BA', 'CE', 'MA', 'PB', 'PE', 'PI', 'RN', 'SE'],
    'Centro-Oeste': ['DF', 'GO', 'MS', 'MT'],
    'Sudeste': ['ES', 'MG', 'RJ', 'SP'],
    'Sul': ['PR', 'RS', 'SC'],
}
REGIAO_DA_UF = {uf: regiao for regiao, ufs in REGIOES.items() for uf in ufs}


def carregar_base(caminho=ARQUIVO_PROCESSADO):
    base = pd.read_parquet(caminho)
    base['dia'] = pd.to_datetime(base['dia'])
    base['sigla_uf'] = base['sigla_uf'].astype('category')
    base['regiao'] = base['sigla_uf'].astype(str).map(REGIAO_DA_UF)
    base['nivel_risco'] = pd.Categorical(base['nivel_risco'], categories=NIVEIS, ordered=True)
    return base


def dividir_por_tempo(base):
    """Treino até setembro de 2024, validação em outubro, teste de novembro de 2024 a fevereiro de 2025."""
    treino = base[base['dia'] <= FIM_TREINO]
    validacao = base[(base['dia'] > FIM_TREINO) & (base['dia'] <= FIM_VALIDACAO)]
    teste = base[base['dia'] > FIM_VALIDACAO]
    return treino, validacao, teste


def persistencia(df):
    """Referência mínima: o nível de hoje é o que os focos de ontem dariam."""
    return pd.Series(np.select([df['focos_ontem'] >= 4, df['focos_ontem'] >= 1], ['Alto', 'Médio'], 'Baixo'),
                     index=df.index)


def decidir(probabilidades, corte_alto, corte_medio):
    """Transforma as probabilidades em nível de risco com duas notas de corte.

    Alto se a probabilidade de Alto passa do seu corte; senão, Médio se a de Médio passa do
    seu corte; senão, Baixo. As notas de corte são escolhidas na validação.
    """
    p = np.asarray(probabilidades)
    return np.where(p[:, 2] >= corte_alto, 'Alto', np.where(p[:, 1] >= corte_medio, 'Médio', 'Baixo'))


def escolher_cortes(y_validacao, probabilidades, grade=np.round(np.arange(0.10, 0.91, 0.05), 2)):
    """Procura, só na validação, as notas de corte que dão o maior F1 macro."""
    melhor = (None, None, -1)
    for corte_alto in grade:
        for corte_medio in grade:
            f1 = f1_score(y_validacao, decidir(probabilidades, corte_alto, corte_medio), average='macro')
            if f1 > melhor[2]:
                melhor = (corte_alto, corte_medio, f1)
    return melhor


def custo_total(y_real, y_previsto, hectares=HECTARES_BASE, custo_equipe=CUSTO_EQUIPE_DIA):
    """Custo em reais: uma equipe por aviso Alto + o prejuízo de cada dia Alto sem aviso.

    Devolve o custo total, o número de avisos Alto e o número de dias Alto sem aviso.
    """
    y_real, y_previsto = np.asarray(y_real), np.asarray(y_previsto)
    avisos = (y_previsto == 'Alto').sum()
    alto_sem_aviso = ((y_real == 'Alto') & (y_previsto != 'Alto')).sum()
    return avisos * custo_equipe + alto_sem_aviso * hectares * PREJUIZO_HECTARE, avisos, alto_sem_aviso


def metricas(y_real, y_previsto, probabilidades=None):
    """As métricas da Etapa 2, em uma linha."""
    y_real, y_previsto = np.asarray(y_real, dtype=object), np.asarray(y_previsto, dtype=object)
    linha = {
        'acuracia': accuracy_score(y_real, y_previsto),
        'f1_macro': f1_score(y_real, y_previsto, average='macro'),
        'precisao_alto': precision_score(y_real, y_previsto, labels=['Alto'], average='macro', zero_division=0),
        'recall_alto': recall_score(y_real, y_previsto, labels=['Alto'], average='macro', zero_division=0),
        'f1_alto': f1_score(y_real, y_previsto, labels=['Alto'], average='macro', zero_division=0),
        'f1_medio': f1_score(y_real, y_previsto, labels=['Médio'], average='macro', zero_division=0),
    }
    if probabilidades is not None:
        linha['auc_roc'] = roc_auc_score(pd.get_dummies(pd.Categorical(y_real, categories=NIVEIS)).values,
                                         np.asarray(probabilidades), average='macro')
    return linha
