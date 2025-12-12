import os  # Biblioteca padrão do Python para trabalhar com caminhos de arquivos e pastas no sistema operacional
from pathlib import Path  # Classe Path facilita trabalhar com caminhos de arquivos/pastas de forma mais organizada
from decimal import Decimal, InvalidOperation  # Usada para trabalhar com números decimais com precisão (útil para dinheiro)

import pandas as pd  # Biblioteca muito usada para trabalhar com tabelas (DataFrames), ideal para dados de planilhas Excel


# ==========================
# CONFIGURAÇÕES PRINCIPAIS
# ==========================

# Diretório raiz padrão da competência (pode ser alterado pelo usuário ao rodar o programa)
# Exemplo: \\10.20.11.20\dp\CELULA DE BENEFICIOS\CONVÊNIO\2025.11
DIRETORIO_RAIZ_PADRAO = r"\\10.20.11.20\dp\CELULA DE BENEFICIOS\CONVÊNIO\2025.11"

# Nome do arquivo Excel final que será gerado com tudo consolidado
NOME_ARQUIVO_CONSOLIDADO = "Consolidado_HAPVIDA.xlsx"


# ==========================
# FUNÇÕES DE APOIO
# ==========================

def listar_arquivos_excel(pasta: Path) -> list[Path]:
    """
    Lista todos os arquivos de Excel (.xlsx e .xls) dentro de uma pasta.
    Retorna uma lista de objetos Path com o caminho de cada arquivo.
    """
    if not pasta.exists():
        print(f"[AVISO] Pasta não encontrada: {pasta}")
        return []

    # Procura arquivos que terminam com .xlsx e .xls
    arquivos = list(pasta.glob("*.xlsx")) + list(pasta.glob("*.xls"))

    if not arquivos:
        print(f"[AVISO] Nenhum arquivo Excel encontrado na pasta: {pasta}")

    return arquivos


def limpar_tabela_basica(tabela: pd.DataFrame) -> pd.DataFrame:
    """
    Faz uma limpeza básica na tabela (DataFrame):
    - remove linhas totalmente em branco
    - remove linhas que são cabeçalhos repetidos
      (linhas onde o conteúdo é igual ao nome das colunas)
    """

    # Se a tabela não existe (None) ou está vazia, apenas devolve como está
    if tabela is None or tabela.empty:
        return tabela

    # Remove linhas completamente vazias (todas as colunas vazias)
    tabela = tabela.dropna(how="all")

    # Função interna para verificar se uma linha é um cabeçalho repetido
    def eh_cabecalho_repetido(linha) -> bool:
        """
        Recebe uma linha da tabela e verifica se
        todos os valores são iguais aos nomes das colunas.
        Se forem iguais, consideramos que essa linha é um cabeçalho repetido.
        """

        # Percorre cada par: nome da coluna (nome_coluna) e valor da célula (valor)
        for nome_coluna, valor in linha.items():
            # Normaliza o texto do nome da coluna:
            # - str(): garante que é string
            # - strip(): tira espaços do começo e do fim
            # - lower(): deixa tudo minúsculo
            texto_coluna_normalizado = str(nome_coluna).strip().lower()

            # Faz a mesma normalização para o valor da célula
            texto_valor_normalizado = str(valor).strip().lower()

            # Se o valor da célula for diferente do nome da coluna,
            # então essa linha NÃO é um cabeçalho repetido
            if texto_valor_normalizado != texto_coluna_normalizado:
                return False

        # Se passou por todas as colunas sem diferença,
        # significa que essa linha é um cabeçalho repetido
        return True

    # Aplica a função 'eh_cabecalho_repetido' em cada linha da tabela
    # axis=1 significa: aplicar função linha a linha (e não coluna a coluna)
    mascara_cabecalho = tabela.apply(eh_cabecalho_repetido, axis=1)

    # A máscara é uma série de True/False.
    # Usamos ~ para negar (True vira False e vice-versa),
    # assim mantemos apenas as linhas que NÃO são cabeçalho repetido.
    tabela = tabela[~mascara_cabecalho]

    # Depois de remover linhas, os índices podem ficar "quebrados" (ex: 0,1,4,7...)
    # reset_index(drop=True) reorganiza para 0,1,2,3...
    # drop=True evita criar uma coluna com o índice antigo.
    tabela = tabela.reset_index(drop=True)

    # Devolve a tabela já limpa
    return tabela


def encontrar_coluna(tabela: pd.DataFrame, nome_alvo: str) -> str | None:
    """
    Procura uma coluna pelo nome, ignorando maiúsculas/minúsculas e espaços.
    Exemplo:
        nome_alvo = "unidade"
        Acha colunas chamadas: "UNIDADE", "Unidade", " unidade " etc.
    Retorna o nome exato da coluna encontrada, ou None se não existir.
    """
    nome_alvo_normalizado = nome_alvo.lower()

    for nome_coluna in tabela.columns:
        if str(nome_coluna).strip().lower() == nome_alvo_normalizado:
            return nome_coluna

    return None


def filtrar_unidade_001(tabela: pd.DataFrame) -> pd.DataFrame:
    """
    Filtra apenas as linhas onde a coluna 'unidade' é igual a '001'.
    Se a coluna 'unidade' não existir, devolve a tabela sem filtro.
    """
    nome_coluna_unidade = encontrar_coluna(tabela, "unidade")

    if nome_coluna_unidade is None:
        # O escopo prevê que algumas planilhas podem não ter coluna "unidade"
        return tabela

    # Converte os valores para string, remove espaços e compara com "001"
    tabela_filtrada = tabela[
        tabela[nome_coluna_unidade].astype(str).str.strip() == "001"
    ].reset_index(drop=True)

    return tabela_filtrada


def filtrar_coluna_a_desconto(tabela: pd.DataFrame) -> pd.DataFrame:
    """
    Filtra linhas onde a PRIMEIRA COLUNA (coluna A da planilha original)
    possui o texto 'Desconto'.

    Essa regra vem do escopo: em MENSALIDADE SAÚDE, os descontos
    ficam marcados na coluna A.
    """
    if tabela is None or tabela.empty:
        return tabela

    # A primeira coluna do DataFrame (equivalente à coluna A no Excel)
    primeira_coluna = tabela.columns[0]

    # Cria uma máscara (True/False) onde o valor normalizado é "desconto"
    mascara = tabela[primeira_coluna].astype(str).str.strip().str.lower() == "desconto"

    tabela_filtrada = tabela[mascara].reset_index(drop=True)

    return tabela_filtrada


def detectar_colunas_monetarias(tabela: pd.DataFrame) -> list[str]:
    """
    Tenta descobrir quais colunas da tabela provavelmente são valores de dinheiro.
    Faz isso olhando o NOME da coluna e procurando palavras-chave,
    como: 'valor', 'vlr', 'mensalidade', 'total' etc.
    """
    palavras_chave = ["valor", "vlr", "preço", "preco", "mensalidade", "total"]
    colunas_encontradas: list[str] = []

    for nome_coluna in tabela.columns:
        nome_coluna_minusculo = str(nome_coluna).lower()

        # Se qualquer palavra-chave estiver no nome da coluna, consideramos monetária
        if any(palavra in nome_coluna_minusculo for palavra in palavras_chave):
            colunas_encontradas.append(nome_coluna)

    return colunas_encontradas


def converter_valor_monetario(valor_original) -> Decimal | None:
    """
    Converte um valor monetário em diferentes formatos de texto para Decimal.

    Exemplos de entradas possíveis:
    - "10000"   → 100,00
    - "100.00"  → 100,00
    - "100,00"  → 100,00
    - "R$ 100,00"
    - valores com pontos e vírgulas misturados

    Retorna:
    - Decimal com o valor convertido, ou
    - None se não conseguir converter.
    """
    # Se for NaN (valor vazio em planilhas), retorna None
    if pd.isna(valor_original):
        return None

    texto = str(valor_original).strip()

    if texto == "":
        return None

    # Remove símbolo de moeda e espaços adicionais
    texto = texto.replace("R$", "").replace(" ", "")

    # Se tiver vírgula e ponto ao mesmo tempo, assume:
    # - ponto é separador de milhar
    # - vírgula é separador de decimal
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        # Se tiver só vírgula, consideramos que ela é o separador decimal
        texto = texto.replace(".", "").replace(",", ".")
    elif "." in texto:
        # Se tiver só ponto, já tratamos como separador decimal
        pass
    else:
        # Se tiver apenas números, assumimos que os dois últimos dígitos são as casas decimais
        if texto.isdigit():
            if len(texto) > 2:
                texto = texto[:-2] + "." + texto[-2:]
            else:
                # Ex: "5" -> "0.05"
                texto = "0." + texto.zfill(2)
        else:
            # Se não for dígito puro, e não entrou em nenhum caso anterior, desiste
            return None

    # Tenta converter o texto para Decimal
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def ajustar_colunas_monetarias(tabela: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica a função 'converter_valor_monetario' em todas as colunas
    que forem identificadas como monetárias.
    """
    if tabela is None or tabela.empty:
        return tabela

    colunas_monetarias = detectar_colunas_monetarias(tabela)

    if not colunas_monetarias:
        return tabela

    for nome_coluna in colunas_monetarias:
        tabela[nome_coluna] = tabela[nome_coluna].apply(converter_valor_monetario)

    return tabela


def tentar_converter_datas(tabela: pd.DataFrame) -> pd.DataFrame:
    """
    Tenta encontrar colunas de data pela nomenclatura,
    por exemplo: 'data', 'data competencia', 'competência' etc.,
    e converte para o tipo datetime do pandas.
    """
    if tabela is None or tabela.empty:
        return tabela

    colunas_data_possiveis: list[str] = []

    for nome_coluna in tabela.columns:
        nome_minusculo = str(nome_coluna).lower()
        if any(palavra in nome_minusculo for palavra in ["data", "competência", "competencia"]):
            colunas_data_possiveis.append(nome_coluna)

    for nome_coluna in colunas_data_possiveis:
        try:
            tabela[nome_coluna] = pd.to_datetime(
                tabela[nome_coluna],
                dayfirst=True,   # dia primeiro (formato brasileiro dd/mm/aaaa)
                errors="coerce"  # se der erro, coloca NaT (data vazia)
            )
        except Exception:
            # Se alguma conversão der erro, apenas ignora aquela coluna
            pass

    return tabela


def unificar_pasta(
    pasta: Path,
    aplicar_filtro_unidade_001: bool = False,
    somente_coluna_a_desconto: bool = False,
    ajustar_moedas: bool = False,
    converter_datas: bool = False,
) -> pd.DataFrame:
    """
    Lê todos os arquivos Excel de uma pasta, faz a limpeza e unifica em um único DataFrame.

    Parâmetros:
    - aplicar_filtro_unidade_001: se True, mantém apenas linhas com unidade = "001"
    - somente_coluna_a_desconto: se True, mantém apenas linhas onde a primeira coluna é "Desconto"
    - ajustar_moedas: se True, tenta converter colunas de valor monetário para Decimal
    - converter_datas: se True, tenta converter colunas com datas para datetime
    """
    arquivos = listar_arquivos_excel(pasta)

    if not arquivos:
        return pd.DataFrame()  # devolve tabela vazia se não houver arquivos

    lista_tabelas: list[pd.DataFrame] = []

    for arquivo in arquivos:
        try:
            # Lê o arquivo Excel inteiro para um DataFrame
            # dtype=str força leitura como texto (evita erros de tipo misto)
            tabela = pd.read_excel(arquivo, dtype=str)
        except Exception as erro:
            print(f"[ERRO] Falha ao ler o arquivo {arquivo}: {erro}")
            continue  # pula para o próximo arquivo

        # Limpa linhas vazias e cabeçalhos repetidos
        tabela = limpar_tabela_basica(tabela)

        # Aplica filtro por unidade (unidade = "001"), se configurado
        if aplicar_filtro_unidade_001:
            tabela = filtrar_unidade_001(tabela)

        # Aplica filtro para manter apenas linhas com "Desconto" na coluna A, se configurado
        if somente_coluna_a_desconto:
            tabela = filtrar_coluna_a_desconto(tabela)

        # Ajusta colunas monetárias, se configurado
        if ajustar_moedas:
            tabela = ajustar_colunas_monetarias(tabela)

        # Converte colunas de datas, se configurado
        if converter_datas:
            tabela = tentar_converter_datas(tabela)

        # Se ainda sobrou algo na tabela, adiciona na lista
        if not tabela.empty:
            # Adiciona uma coluna para saber de qual arquivo veio cada linha
            tabela["__arquivo_origem"] = str(arquivo.name)
            lista_tabelas.append(tabela)

    if not lista_tabelas:
        return pd.DataFrame()

    # Junta todas as tabelas em uma só, empilhando as linhas
    tabela_unificada = pd.concat(lista_tabelas, ignore_index=True)

    return tabela_unificada


def montar_totalizador(dicionario_abas: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Cria uma tabela "TOTALIZADOR" com os somatórios das colunas monetárias de cada aba.

    Para cada aba:
    - identifica colunas monetárias
    - soma os valores
    - registra na tabela de resumo
    """
    linhas_totalizador: list[dict] = []

    for nome_aba, tabela in dicionario_abas.items():
        if tabela is None or tabela.empty:
            continue

        colunas_monetarias = detectar_colunas_monetarias(tabela)

        for nome_coluna in colunas_monetarias:
            try:
                # Garante que cada valor está em Decimal, convertendo se necessário
                serie_valores = tabela[nome_coluna].apply(
                    lambda v: converter_valor_monetario(v)
                    if not isinstance(v, Decimal)
                    else v
                )

                # Soma apenas valores não nulos
                total = sum(valor for valor in serie_valores if valor is not None)

                linhas_totalizador.append(
                    {
                        "Aba": nome_aba,
                        "Campo": nome_coluna,
                        # Converte para float na hora de gravar (Excel lida bem com float)
                        "Total": float(total),
                    }
                )
            except Exception as erro:
                print(f"[AVISO] Não foi possível totalizar {nome_aba}.{nome_coluna}: {erro}")

    if not linhas_totalizador:
        return pd.DataFrame()

    tabela_totalizador = pd.DataFrame(linhas_totalizador)
    return tabela_totalizador


# ==========================
# FLUXO PRINCIPAL DO PROGRAMA
# ==========================

def main():
    """
    Função principal do programa.
    Ela:
    - pergunta (ou usa padrão) o diretório raiz da competência
    - monta os caminhos das subpastas
    - processa cada tipo de planilha
    - gera um arquivo Excel consolidado com várias abas
    """

    # Pede ao usuário o diretório raiz, ou usa o padrão se ele só apertar ENTER
    entrada_usuario = input(
        f"Informe o diretório raiz da competência "
        f"(ENTER para usar o padrão)\n[{DIRETORIO_RAIZ_PADRAO}]: "
    ).strip()

    if entrada_usuario:
        diretorio_raiz = Path(entrada_usuario)
    else:
        diretorio_raiz = Path(DIRETORIO_RAIZ_PADRAO)

    # Monta os caminhos das pastas principais conforme o escopo
    pasta_saude = diretorio_raiz / "HAPVIDA SAÚDE"
    pasta_odonto = diretorio_raiz / "HAPVIDA ODONTO"

    # Subpastas de SAÚDE
    pasta_saude_conferencia = pasta_saude / "CONFERENCIA"
    pasta_saude_coparticipacao = pasta_saude / "COPARTICIPAÇÃO"
    pasta_saude_mensalidade = pasta_saude / "MENSALIDADE"

    # Subpastas de ODONTO
    pasta_odonto_conferencia = pasta_odonto / "CONFERENCIA"
    pasta_odonto_mensalidade = pasta_odonto / "MENSALIDADE"

    # Pasta onde será salvo o arquivo consolidado
    pasta_consolidador = pasta_saude / "Consolidador"
    pasta_consolidador.mkdir(parents=True, exist_ok=True)

    caminho_arquivo_saida = pasta_consolidador / NOME_ARQUIVO_CONSOLIDADO

    print("\n=== INICIANDO PROCESSAMENTO ===\n")
    print(f"Diretório raiz informado: {diretorio_raiz}")
    print(f"Arquivo de saída será gerado em: {caminho_arquivo_saida}\n")

    # ==========================
    # PROCESSAMENTO POR PASTA
    # ==========================

    # SAÚDE - CONFERENCIA
    print("[INFO] Processando SAUDE_CONFERENCIA...")
    tabela_saude_conferencia = unificar_pasta(
        pasta_saude_conferencia,
        aplicar_filtro_unidade_001=True,   # filtra unidade = 001
        somente_coluna_a_desconto=False,
        ajustar_moedas=False,
        converter_datas=False,
    )

    # SAÚDE - COPARTICIPAÇÃO
    print("[INFO] Processando SAUDE_COPARTICIPACAO...")
    tabela_saude_coparticipacao = unificar_pasta(
        pasta_saude_coparticipacao,
        aplicar_filtro_unidade_001=True,   # filtra unidade = 001
        somente_coluna_a_desconto=False,
        ajustar_moedas=True,               # ajusta valores monetários
        converter_datas=False,
    )

    # SAÚDE - MENSALIDADE
    print("[INFO] Processando SAUDE_MENSALIDADE...")
    tabela_saude_mensalidade = unificar_pasta(
        pasta_saude_mensalidade,
        aplicar_filtro_unidade_001=False,
        somente_coluna_a_desconto=True,    # mantém apenas linhas com "Desconto" na coluna A
        ajustar_moedas=True,
        converter_datas=False,
    )

    # ODONTO - CONFERENCIA
    print("[INFO] Processando ODONTO_CONFERENCIA...")
    tabela_odonto_conferencia = unificar_pasta(
        pasta_odonto_conferencia,
        aplicar_filtro_unidade_001=True,
        somente_coluna_a_desconto=False,
        ajustar_moedas=False,
        converter_datas=False,
    )

    # ODONTO - MENSALIDADE
    print("[INFO] Processando ODONTO_MENSALIDADE...")
    tabela_odonto_mensalidade = unificar_pasta(
        pasta_odonto_mensalidade,
        aplicar_filtro_unidade_001=True,
        somente_coluna_a_desconto=False,
        ajustar_moedas=True,
        converter_datas=True,  # inclui as datas de competência etc.
    )

    # Dicionário com o nome de cada aba e sua tabela correspondente
    dicionario_abas = {
        "SAUDE_CONFERENCIA": tabela_saude_conferencia,
        "SAUDE_COPARTICIPACAO": tabela_saude_coparticipacao,
        "SAUDE_MENSALIDADE": tabela_saude_mensalidade,
        "ODONTO_CONFERENCIA": tabela_odonto_conferencia,
        "ODONTO_MENSALIDADE": tabela_odonto_mensalidade,
    }

    # Cria a aba TOTALIZADOR com somatórios
    print("[INFO] Montando TOTALIZADOR...")
    tabela_totalizador = montar_totalizador(dicionario_abas)
    dicionario_abas["TOTALIZADOR"] = tabela_totalizador

    # ==========================
    # GRAVAÇÃO DO ARQUIVO EXCEL
    # ==========================

    print(f"[INFO] Gravando arquivo consolidado em: {caminho_arquivo_saida}")

    # Usa o ExcelWriter do pandas com o motor "openpyxl"
    with pd.ExcelWriter(caminho_arquivo_saida, engine="openpyxl") as escritor_excel:
        for nome_aba, tabela in dicionario_abas.items():
            if tabela is None or tabela.empty:
                print(f"[AVISO] Aba {nome_aba} está vazia, não será criada.")
                continue

            # sheet_name aceita no máximo 31 caracteres no Excel
            escritor_excel.write_cells
            tabela.to_excel(
                escritor_excel,
                sheet_name=nome_aba[:31],  # garante que o nome da aba não passa de 31 caracteres
                index=False                # não grava a coluna de índice no Excel
            )

    print("\n=== PROCESSO CONCLUÍDO ===")
    print(f"Arquivo gerado com sucesso em: {caminho_arquivo_saida}")


# Este bloco garante que a função main() só seja executada
# quando o arquivo for rodado diretamente (e não importado como módulo)
if __name__ == "__main__":
    main()
