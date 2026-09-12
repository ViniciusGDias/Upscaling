# ⬆ Video Upscaler 4K

Aplicativo desktop simples para fazer upscaling de vídeos para 4K usando FFmpeg.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FFmpeg](https://img.shields.io/badge/FFmpeg-required-green)

## 🚀 Como Usar

1. **Instale as dependências:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Certifique-se que o FFmpeg está instalado:**
   - Baixe em [ffmpeg.org](https://ffmpeg.org/download.html)
   - Adicione ao PATH do sistema

3. **Execute o app:**
   ```bash
   python app.py
   ```

4. **Selecione um vídeo**, configure as opções e clique em **Iniciar Upscaling**!

## ⚙️ Configurações Disponíveis

### Resoluções de Saída
| Resolução | Pixels |
|-----------|--------|
| 4K | 3840×2160 |
| 2K QHD | 2560×1440 |
| Full HD | 1920×1080 |
| HD | 1280×720 |

### Algoritmos de Escala
| Algoritmo | Descrição |
|-----------|-----------|
| **Lanczos** | Melhor qualidade, mais lento |
| **Bicubic** | Boa qualidade, bom desempenho |
| **Bilinear** | Rápido, qualidade aceitável |
| **Spline** | Balanceado entre qualidade e velocidade |

### Qualidade de Saída
| Preset | CRF | Velocidade |
|--------|-----|-----------|
| Alta | 18 | Lento |
| Média | 23 | Médio |
| Baixa | 28 | Rápido |

## 📁 Formatos Suportados
MP4, MKV, AVI, MOV, WMV, FLV, WebM, M4V, MPEG, TS

## 🛠️ Estrutura do Projeto
```
Upscaling/
├── app.py           # Interface gráfica (CustomTkinter)
├── upscaler.py      # Engine de upscaling (FFmpeg)
├── requirements.txt # Dependências Python
└── README.md        # Este arquivo
```
