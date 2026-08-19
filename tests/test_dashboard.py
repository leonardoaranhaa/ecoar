"""Guardas de regressão do painel.

Não substituem abrir o navegador — cobrem dois erros que já aconteceram e que
não aparecem em teste de API nenhum, porque só existem no lado do navegador.
"""

from pathlib import Path

PAINEL = Path(__file__).resolve().parents[1] / "dashboard"


def test_atributo_hidden_e_forcado_no_css():
    """`display` numa classe vence o display:none padrão de [hidden].

    Sem esta regra, a tela de acesso continua visível acima do painel depois do
    login — e o operador convive com um formulário de token na tela o dia todo.
    """
    css = (PAINEL / "estilo.css").read_text(encoding="utf-8")
    assert "[hidden]" in css and "display: none !important" in css


def test_midia_e_carregada_por_fetch_com_token():
    """O navegador não manda cabeçalho de autenticação em <img> nem <audio>.

    Se a mídia voltar a ser referenciada direto por `src`, ela responde 401 e o
    operador vê a fila sem imagem e sem áudio — justamente o que ele precisa
    para decidir.
    """
    import re

    js = (PAINEL / "painel.js").read_text(encoding="utf-8")

    assert "data-src" in js
    assert "carregarMidia" in js
    # `data-src` também contém "src=", daí a exclusão explícita do prefixo.
    assert not re.search(r'(?<!data-)src="/v1/', js), (
        "mídia não pode ser referenciada direto por src: o navegador não envia "
        "o cabeçalho de autenticação e a resposta vira 401"
    )


def test_painel_escapa_texto_vindo_da_api():
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    assert "function texto(" in js
    assert "&lt;" in js and "&amp;" in js


def test_paleta_segue_a_identidade_do_produto():
    css = (PAINEL / "estilo.css").read_text(encoding="utf-8")
    assert "#f5a623" in css.lower(), "âmbar para pendente"
    assert "#2ecc71" in css.lower(), "verde para confirmado"
    assert "#ff6b35" in css.lower(), "laranja da marca"


def test_painel_nao_expoe_caminho_de_arquivo_interno():
    """O painel é lido por operador de prefeitura, não por quem mantém o código.

    Referência a `docs/DECISIONS.md`, `config/no-01.yaml` ou numeração interna
    de roteiro é anotação de desenvolvimento: numa tela de cliente ela não
    ajuda ninguém e ainda entrega que o texto foi escrito para outro público.
    Comentário de código pode citar tudo isso à vontade — o que este teste
    protege é só o que vai para a tela.
    """
    import re

    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    # Remove comentários de bloco e de linha: só sobra o que pode virar tela.
    visivel = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    visivel = re.sub(r"^\s*//.*$", "", visivel, flags=re.M)

    for proibido in ("docs/", "config/no-", "DECISIONS.md", "manual-tecnico"):
        assert proibido not in visivel, (
            f"{proibido!r} aparece em texto de tela do painel; "
            "isso é referência interna, não informação para o operador"
        )
