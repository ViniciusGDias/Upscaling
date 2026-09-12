# 🎩 Urahara Studio

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/Python-3.10+-yellow)
![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-black)
![License](https://img.shields.io/badge/License-MIT-green)

**Urahara Studio** é uma suíte de inteligência artificial e edição de vídeo para criadores de conteúdo, canais de anime e editores de vídeo.

---

## ⚡ Funcionalidades Integradas

1. **⬆️ Upscaling 4K**: Super-resolução para vídeos e animes com **Real-CUGAN Vulkan** (ultrarrápido) e FFmpeg.
2. **🎬 Diretor IA**: Curadoria de momentos épicos (Top 3 e Smart Cortes) com mapeamento de timestamps via Whisper e IA.
3. **✂️ Refinador Mastercut**: Eliminação cirúrgica de silêncios mortos com proteção anti-corte excessivo (Safety Floor).
4. **🎧 Separação de Áudio**: Isolamento de vocais, instrumentais e efeitos sonoros com **Demucs (Meta AI)**.
5. **📸 Analisador Instagram Reels**: Análise de estética, retenção, ganchos e gerador de legendas/hashtags prontas.
6. **▶️ Analisador YouTube Shorts**: Otimização de retenção, 5 títulos virais, legendas de impacto e comentários fixados.
7. **⛩️ Anime Finder**: Busca contextual de cenas e episódios com integração oficial Kitsu/MAL/TVMaze.
8. **⚙️ Configurações & Motores**: Gerenciador visual de chaves (Gemini, Groq, OpenRouter), download automático de FFmpeg com 1 clique e verificador de atualizações.

---

## 🚀 Como Iniciar (Usuário / Desenvolvedor)

### 1. Instalar Dependências
```bash
pip install -r requirements.txt
```

### 2. Configurar Chaves de API
Copie o arquivo `.env.example` para `.env`:
```bash
cp .env.example .env
```
Abra o aplicativo ou edite o `.env` com sua chave gratuita do **Google Gemini** ([Google AI Studio](https://aistudio.google.com/apikey)).

### 3. Executar o Aplicativo
```bash
python app.py
```

---

## 📦 Gerar o Executável e Instalador

Para compilar o aplicativo para distribuição:
```bash
python make_installer.py
```
Isso gerará:
- `dist/Urahara.exe` (Executável sem terminal / janela nativa com ícone oficial)
- `setup_output/Urahara_v1.0.0_Portable.zip` (Pacote portátil pronto para publicação)
- `setup_output/Urahara_Setup_v1.0.0.exe` (Instalador Inno Setup)

---

## 🔒 Segurança
- O arquivo `.env` com suas chaves pessoais **nunca** é enviado para o repositório público (protegido pelo `.gitignore`).
- As requisições de IA conectam-se de forma direta e segura do computador do usuário aos servidores oficiais.
