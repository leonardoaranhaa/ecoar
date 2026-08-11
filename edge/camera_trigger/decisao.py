"""A tabela de decisão: acionar, ambíguo ou descartar.

O módulo mais curto do sistema e o de maior peso jurídico. Três propriedades
que não são negociáveis:

**Determinístico.** Nenhum modelo de linguagem, nenhuma heurística não
registrada, nenhum estado interno. Mesma entrada + mesma versão de política =
mesma saída, sempre.

**Versionado.** Cada decisão grava a versão da política que a produziu. Sem
isso, é impossível responder "por que este evento acionou e aquele não" seis
meses depois — e essa é exatamente a pergunta que uma contestação faz.

**Rastreável.** A decisão não sai como um veredito só: sai com todas as regras
avaliadas, cada uma com o que se esperava, o que se mediu e se passou. É o que
transforma "o sistema decidiu" em "o sistema decidiu por estas razões".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from edge.audio_capture.spl import EstimativaSPL
from edge.classifier.base import Predicao
from edge.config import ConfigGatilho
from edge.localization.doa import EstimativaDOA


class Acao(str, Enum):
    ACIONAR = "acionar"
    AMBIGUO = "ambiguo"
    DESCARTAR = "descartar"


@dataclass(frozen=True)
class Regra:
    nome: str
    atendida: bool
    esperado: str
    medido: str

    def como_dict(self) -> dict[str, object]:
        return {
            "nome": self.nome,
            "atendida": self.atendida,
            "esperado": self.esperado,
            "medido": self.medido,
        }


@dataclass(frozen=True)
class Decisao:
    acao: Acao
    motivo: str
    versao_politica: str
    regras: tuple[Regra, ...]
    dentro_do_campo_de_visao: bool

    @property
    def aciona_camera(self) -> bool:
        return self.acao is Acao.ACIONAR

    @property
    def gera_evento(self) -> bool:
        """Ambíguo também vira evento — sem imagem, e marcado para revisão.

        Descartar em silêncio um som que quase confirmou é jogar fora
        justamente o dado que mostraria o classificador precisando de ajuste.
        """
        return self.acao in (Acao.ACIONAR, Acao.AMBIGUO)

    def como_dict(self) -> dict[str, object]:
        return {
            "acao": self.acao.value,
            "motivo": self.motivo,
            "versao_politica": self.versao_politica,
            "dentro_do_campo_de_visao": self.dentro_do_campo_de_visao,
            "regras": [regra.como_dict() for regra in self.regras],
        }


def diferenca_angular(a: float, b: float) -> float:
    """Menor diferença entre dois azimutes, em graus (0 a 180)."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def decidir(
    predicao: Predicao | None,
    doa: EstimativaDOA | None,
    spl: EstimativaSPL | None,
    politica: ConfigGatilho,
) -> Decisao:
    """Aplica a política. A ordem das regras faz parte da política."""

    # Fail-closed (D8): subsistema fora do ar não vira "provavelmente nada".
    if predicao is None:
        return _ambiguo(
            "classificador indisponível — evento registrado sem acionar a câmera",
            politica,
            (Regra("classificador disponível", False, "predição presente", "ausente"),),
            dentro=False,
        )

    score = predicao.score_alvo
    regras: list[Regra] = [
        Regra(
            "classificador disponível",
            True,
            "predição presente",
            f"{predicao.modelo} {predicao.versao_modelo}",
        ),
        Regra(
            "score da classe alvo acima do limiar de acionamento",
            score >= politica.score_aciona,
            f">= {politica.score_aciona:.2f}",
            f"{score:.3f} (classe {predicao.classe})",
        ),
    ]

    if spl is not None:
        regras.append(
            Regra(
                "nível sonoro acima do piso do nó",
                spl.db >= politica.spl_db_minimo,
                f">= {politica.spl_db_minimo:.1f} dB estimado",
                f"{spl.db:.1f} dB (sem valor legal)",
            )
        )

    if doa is None:
        regras.append(
            Regra("localização disponível", False, "ângulo estimado", "ausente")
        )
        return _ambiguo(
            "sem ângulo estimado: não é possível associar o som a um veículo",
            politica,
            tuple(regras),
            dentro=False,
        )

    desvio = diferenca_angular(doa.azimute_graus, politica.azimute_camera_graus)
    dentro_do_campo = desvio <= politica.campo_visao_graus / 2.0

    regras += [
        Regra(
            "confiança da localização",
            doa.confianca >= politica.doa_confianca_minima,
            f">= {politica.doa_confianca_minima:.2f}",
            f"{doa.confianca:.3f}",
        ),
        Regra(
            "margem angular estreita",
            doa.margem_graus <= politica.doa_margem_maxima_graus,
            f"<= {politica.doa_margem_maxima_graus:.1f}°",
            f"±{doa.margem_graus:.1f}°",
        ),
        Regra(
            "fonte dentro do campo de visão da câmera",
            dentro_do_campo,
            f"desvio <= {politica.campo_visao_graus / 2.0:.1f}° do eixo da câmera",
            f"{desvio:.1f}° (fonte em {doa.azimute_graus:.1f}°)",
        ),
    ]

    todas_atendidas = all(regra.atendida for regra in regras)
    if todas_atendidas:
        return Decisao(
            acao=Acao.ACIONAR,
            motivo=(
                f"{predicao.classe} com score {score:.2f} em {doa.azimute_graus:.0f}° "
                f"(±{doa.margem_graus:.0f}°), dentro do campo de visão"
            ),
            versao_politica=politica.versao_politica,
            regras=tuple(regras),
            dentro_do_campo_de_visao=dentro_do_campo,
        )

    if score >= politica.score_ambiguo:
        nao_atendidas = [regra.nome for regra in regras if not regra.atendida]
        return _ambiguo(
            "score compatível, mas " + "; ".join(nao_atendidas),
            politica,
            tuple(regras),
            dentro=dentro_do_campo,
        )

    return Decisao(
        acao=Acao.DESCARTAR,
        motivo=(
            f"score da classe alvo {score:.2f} abaixo do piso de revisão "
            f"{politica.score_ambiguo:.2f} (classificado como {predicao.classe})"
        ),
        versao_politica=politica.versao_politica,
        regras=tuple(regras),
        dentro_do_campo_de_visao=dentro_do_campo,
    )


def _ambiguo(
    motivo: str, politica: ConfigGatilho, regras: tuple[Regra, ...], dentro: bool
) -> Decisao:
    return Decisao(
        acao=Acao.AMBIGUO,
        motivo=motivo,
        versao_politica=politica.versao_politica,
        regras=regras,
        dentro_do_campo_de_visao=dentro,
    )
