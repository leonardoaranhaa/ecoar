"""Plataforma de gestão: priorização, métricas, modelo e exportação.

A tela de priorização é o entregável central em modo de triagem, e por isso é a
home do dashboard. As demais telas dão a inteligência operacional em volta.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response

from backend import db
from backend.config import ConfigBackend
from backend.seguranca import Identidade, autenticar_operador


def criar_rotas(config: ConfigBackend, conexao) -> APIRouter:
    rotas = APIRouter(prefix="/v1", tags=["gestão"])
    operador_autenticado = autenticar_operador(config)

    @rotas.get("/priorizacao")
    def priorizacao(identidade: Identidade = Depends(operador_autenticado)):
        """Mapa de calor hora × dia da semana + ranking de pontos.

        Só eventos confirmados por humano entram (D2): priorizar sobre evento
        pendente ou rejeitado mandaria a fiscalização para o lugar errado.
        """
        return {
            "hora_dia": db.priorizacao_hora_dia(conexao),
            "por_no": db.priorizacao_por_no(conexao),
            "observacao": (
                "Baseado apenas em eventos confirmados por operador. Em modo de "
                "triagem, este é o dado de priorização — não gera autuação."
            ),
        }

    @rotas.get("/metricas")
    def metricas(identidade: Identidade = Depends(operador_autenticado)):
        rejeicao = db.taxa_de_rejeicao(conexao)
        return {
            "por_dia": db.eventos_por_dia(conexao),
            "rejeicao": rejeicao,
            "contagem": db.contar_por_status(conexao),
            # Sem números de custo inventados: a comparação com blitz exige o
            # custo real que só o município tem. O que se entrega é o volume
            # operacional; a conversão em economia é do contratante.
            "nota_custo": (
                "A comparação de custo com blitz manual depende do custo de "
                "operação informado pelo município. O sistema entrega o volume "
                "operacional; a economia é calculada com o dado do contratante."
            ),
        }

    @rotas.get("/modelo/versoes")
    def modelo_versoes(identidade: Identidade = Depends(operador_autenticado)):
        return {
            "versoes": db.versoes_de_modelo(conexao),
            "observacao": (
                "Versões derivadas do que a evidência registrou. Promoção e "
                "reversão de modelo entram com o pipeline de re-treino (etapa 9), "
                "que depende de volume real de eventos confirmados."
            ),
        }

    @rotas.get("/nos/modos")
    def modos_dos_nos(identidade: Identidade = Depends(operador_autenticado)):
        """Modo vigente por nó — informativo, para a tela de configurações.

        O modo é declarado na configuração do nó, não alterável pelo painel: em
        `modo=autuacao` ele exige instrumento certificado e base normativa
        federal, que hoje não existe (docs/legal/inmetro.md). Apresentar um
        botão de troca aqui seria prometer o que o sistema não entrega.
        """
        return {
            "nos": [
                {"no_id": linha["no_id"], "modo": linha["modo"]}
                for linha in db.listar_nos(conexao)
            ],
            "autuacao_liberada": False,
            "motivo_autuacao_bloqueada": (
                "Não há regulamentação federal (Inmetro/CONTRAN) que valide multa "
                "automática por ruído. O modo de autuação existe e está desligado; "
                "habilitá-lo é decisão de configuração do nó, com instrumento "
                "certificado declarado. Ver docs/legal/inmetro.md."
            ),
        }

    @rotas.get("/trafego")
    def trafego(identidade: Identidade = Depends(operador_autenticado)):
        """Contagem e classificação de tráfego (roadmap modular).

        Dado operacional de mobilidade, sem placa (D10) e sem passar pela fila
        de revisão (D2 não se aplica: não há decisão de infração aqui).
        """
        return {
            "por_tipo": db.trafego_por_tipo(conexao),
            "por_hora": db.trafego_hora_dia(conexao),
            "por_no": db.trafego_por_no(conexao),
            "observacao": (
                "Contagem aproximada de tráfego por tipo de veículo, reaproveitando "
                "a câmera já instalada. Dado de planejamento de mobilidade — não gera "
                "autuação nem entra na priorização de fiscalização de ruído."
            ),
        }

    @rotas.get("/priorizacao/relatorio", response_class=Response)
    def relatorio(identidade: Identidade = Depends(operador_autenticado)):
        """Relatório de priorização em HTML pronto para imprimir em PDF.

        HTML e não PDF binário de propósito: sem dependência de biblioteca de
        PDF no servidor, e o operador imprime pelo próprio navegador. O conteúdo
        é o dado de priorização que ele leva para a equipe de fiscalização.
        """
        html = _montar_relatorio(
            hora_dia=db.priorizacao_hora_dia(conexao),
            por_no=db.priorizacao_por_no(conexao),
            rejeicao=db.taxa_de_rejeicao(conexao),
        )
        return Response(content=html, media_type="text/html")

    return rotas


DIAS = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"]


def _montar_relatorio(hora_dia: list[dict], por_no: list[dict], rejeicao: dict) -> str:
    grade = {(linha["dia"], linha["hora"]): linha["total"] for linha in hora_dia}
    maximo = max(grade.values(), default=0)

    linhas_no = "".join(
        f"<tr><td>{_e(no['no_id'])}</td><td>{_e(no.get('descricao') or '—')}</td>"
        f"<td class='num'>{no['confirmados']}</td></tr>"
        for no in por_no
    ) or "<tr><td colspan='3'>Nenhum evento confirmado ainda.</td></tr>"

    celulas = []
    for hora in range(24):
        celulas.append(f"<tr><th>{hora:02d}h</th>")
        for dia in range(7):
            total = grade.get((dia, hora), 0)
            intensidade = (total / maximo) if maximo else 0
            fundo = f"background: rgba(245,166,35,{0.12 + 0.88 * intensidade:.2f})" if total else ""
            celulas.append(f"<td style='{fundo}' title='{DIAS[dia]} {hora:02d}h: {total}'>"
                           f"{total or ''}</td>")
        celulas.append("</tr>")
    grade_html = "".join(celulas)

    cabecalho_dias = "".join(f"<th>{d[:3]}</th>" for d in DIAS)
    gerado = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    taxa = rejeicao.get("taxa_rejeicao")
    taxa_txt = f"{taxa * 100:.1f}%" if taxa is not None else "—"

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>ECOAR — Relatório de priorização</title>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; color: #14181b; margin: 32px; }}
  h1 {{ font-family: Manrope, sans-serif; letter-spacing: 0.02em; }}
  .selo {{ color: #7E5200; font-weight: 600; }}
  table {{ border-collapse: collapse; margin: 16px 0; }}
  td, th {{ border: 1px solid #d4d8dc; padding: 4px 8px; text-align: center; font-size: 12px; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .aviso {{ background: #fdf3e2; border-left: 3px solid #F5A623; padding: 10px 14px; font-size: 13px; }}
  footer {{ margin-top: 24px; color: #667; font-size: 12px; }}
  @media print {{ body {{ margin: 0; }} }}
</style></head><body>
  <h1>ECOAR — Relatório de priorização</h1>
  <p class="selo">Modo de triagem · dado para direcionar fiscalização humana</p>
  <p>Gerado em {gerado}</p>

  <div class="aviso">
    Baseado apenas em eventos <strong>confirmados por operador</strong>. Este
    relatório não constitui auto de infração. O nível sonoro estimado pelo
    array não tem valor legal de medição.
  </div>

  <h2>Quando o problema é pior</h2>
  <table>
    <tr><th></th>{cabecalho_dias}</tr>
    {grade_html}
  </table>

  <h2>Onde o problema é pior</h2>
  <table>
    <tr><th>Nó</th><th>Local</th><th>Eventos confirmados</th></tr>
    {linhas_no}
  </table>

  <p>Taxa de rejeição na revisão: <strong>{taxa_txt}</strong>
     ({rejeicao.get('rejeitados', 0)} de {rejeicao.get('decididos', 0)} decididos)</p>

  <footer>Studio Cerne · ECOAR · fiscalização sonora inteligente</footer>
</body></html>"""


def _e(texto) -> str:
    return (
        str(texto)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
