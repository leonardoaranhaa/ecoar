# vision/trajectory — desambiguação de tráfego simultâneo

Quando dois veículos passam próximos, o ângulo estimado pelo array
(`edge/localization`) sozinho pode não separar um do outro.

Este módulo cruza a posição e a trajetória detectadas na imagem com o ângulo
acústico e a sua margem de erro, e responde: os dois são compatíveis com a mesma
fonte, ou apenas um é?

Se a resposta não for clara, o evento é marcado como ambíguo. Um sistema que
escolhe o veículo mais provável sem conseguir provar a escolha é exatamente o
que perde na contestação.
