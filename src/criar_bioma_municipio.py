"""Cria a tabela com o bioma de cada município, usada só no teste de viés da Etapa 3.

O bioma não entra como feature (ver 01_eda.ipynb), porque só é registrado junto de um foco.
Para medir viés, ele serve bem: cada município recebe o bioma que mais aparece nos seus focos.
Municípios sem nenhum foco ficam fora da tabela e aparecem como "sem foco registrado".
"""
from consolidar_base import ARQUIVO_PROCESSADO, conectar

ARQUIVO_BIOMA = ARQUIVO_PROCESSADO.parent / 'bioma_municipio.csv'


def criar_bioma_municipio(caminho=ARQUIVO_BIOMA):
    con = conectar()
    con.execute(f"""
        COPY (
            SELECT id_municipio,
                   MODE(bioma) AS bioma           -- o bioma mais frequente nos focos do município
            FROM queimadas
            WHERE id_municipio IS NOT NULL AND bioma IS NOT NULL
            GROUP BY id_municipio
            ORDER BY id_municipio
        ) TO '{caminho.as_posix()}' (HEADER, DELIMITER ',')
    """)


if __name__ == '__main__':
    criar_bioma_municipio()
