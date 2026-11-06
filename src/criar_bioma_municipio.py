"""Cria a tabela com o bioma de cada município, usada só no teste de viés da Etapa 3.

O bioma não entra como feature (ver 01_eda.ipynb), porque só é registrado junto de um foco.
Para medir viés, ele serve bem: cada município recebe o bioma que mais aparece nos seus focos.
Municípios sem nenhum foco ficam fora da tabela e aparecem como "sem foco registrado".
"""
from consolidar_base import ARQUIVO_PROCESSADO, conectar

ARQUIVO_BIOMA = ARQUIVO_PROCESSADO.parent / 'bioma_municipio.csv'


def criar_bioma_municipio():
    con = conectar()
    con.execute(f"""
        COPY (
            SELECT id_municipio, bioma
            FROM queimadas
            WHERE id_municipio IS NOT NULL AND bioma IS NOT NULL
            GROUP BY id_municipio, bioma
            -- fica o bioma mais frequente nos focos do município; no empate, o primeiro em ordem alfabética
            QUALIFY ROW_NUMBER() OVER (PARTITION BY id_municipio ORDER BY COUNT(*) DESC, bioma) = 1
            ORDER BY id_municipio
        ) TO '{ARQUIVO_BIOMA.as_posix()}' (HEADER, DELIMITER ',')
    """)


if __name__ == '__main__':
    criar_bioma_municipio()
