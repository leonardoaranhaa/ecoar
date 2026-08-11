import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from edge.config import ConfigNo, de_dict  # noqa: E402


def config_base(**sobrescritas) -> dict:
    """Configuração mínima válida de nó, em modo de triagem."""
    dados = {
        "no": {"id": "teste-01", "geolocalizacao": {"latitude": -22.3, "longitude": -49.06}},
        "modo": "triagem",
        "audio": {
            "taxa_amostragem": 16000,
            "canais": 4,
            "buffer_segundos": 5,
            "bloco_amostras": 1024,
            "fonte": {"tipo": "sintetica", "tempo_real": False, "perfil": "escapamento"},
            "calibracao": {"offset_db": 94.0, "ponderacao": "A", "referencia": "teste"},
        },
        "array": {"raio_m": 0.045, "n_microfones": 4},
        "sonometro": {"tipo": "ausente"},
    }
    dados.update(sobrescritas)
    return dados


@pytest.fixture
def config() -> ConfigNo:
    return de_dict(config_base())
