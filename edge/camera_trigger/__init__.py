"""Decisão de acionamento e captura de imagem."""

from edge.camera_trigger.acionador import AcionadorCamera, ResultadoAcionamento
from edge.camera_trigger.camera import (
    PANORAMICA,
    PLACA,
    Camera,
    CameraIndisponivel,
    CameraOpenCV,
    CameraSimulada,
    CapturaImagem,
    criar_camera,
    escrever_png,
)
from edge.camera_trigger.decisao import Acao, Decisao, Regra, decidir, diferenca_angular

__all__ = [
    "Acao",
    "AcionadorCamera",
    "Camera",
    "CameraIndisponivel",
    "CameraOpenCV",
    "CameraSimulada",
    "CapturaImagem",
    "Decisao",
    "PANORAMICA",
    "PLACA",
    "Regra",
    "ResultadoAcionamento",
    "criar_camera",
    "decidir",
    "diferenca_angular",
    "escrever_png",
]
