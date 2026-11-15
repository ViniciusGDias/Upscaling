# Task: Variedades de Recorte Mangá (Jitter Motion) + Múltiplas Opções Emocionais no Refinador

> **Status**: Planejado & Pronto para Execução
> **Data**: 2026-10-26
> **Prioridade**: Alta / Preservação Total de Estabilidade

---

## 🎯 Objetivos da Tarefa

1. **Parte 1 (Studio - Recorte Mangá com Motion Jitter & Estilos Modernos)**:
   - Adicionar curvas e físicas de animação inspiradas no [Jitter.video](https://jitter.video/templates/text/):
     - `Elastic Spring / Pop Overshoot` (física de mola realista com decaimento suave).
     - `Masked Slide-Up & Snap` (revelação vertical a partir de máscara com trava elástica).
     - `Blur-In & Crisp Focus` (transição de desfoque inicial para foco nítido e impacto).
     - `Kinetic Tracking Expand/Shrink` (letras convergindo para o ponto focal).
     - `RGB Split & Cyber Glitch` (aberração cromática estilizada de mangá).
   - Expandir a biblioteca de feelings visuais em `manga_fx_engine.py` e `anime_fx_analyzer.py`:
     - `domain_dark` (Expansão de Domínio / Nanquim Cósmico Violeta).
     - `blade_stream` (Lâmina de Água / Respiração Shonen Ciano).
     - `blood_ink` (Berserk / Nanquim Carmesim Espirrado).
     - `cyber_glitch` (Glitch Nanquim Cyber / Scanlines).
     - `comic_halftone` (Pop Shonen Reticulado Clássico).

2. **Parte 2 (Refinador - Múltiplas Opções Adaptativas ao Tom da Cena)**:
   - Em vídeos longos (> 75s / 3 a 4 min), permitir que a IA identifique e gere **de 1 a 3 opções de vídeos refinados independentes** (cada um com seu próprio início, desenvolvimento e clímax de até 59s).
   - **Sensibilidade ao Tom**: As opções não forçam uma ordem rígida; adaptam-se ao teor dramático da cena (seja puramente triste/emocional, comédia, ação intensa ou suspense).
   - **Renderização Multicandidata**: FFmpeg renderiza as opções geradas (`_refinado_op1.mp4`, `_refinado_op2.mp4`, etc.).
   - **Interface com Seletor de Opções no Refinador**: Abas dinâmicas no card de resultado permitindo alternar entre as opções, ler seus roteiros, dar play e enviar a opção desejada para o Studio.
   - **Retrocompatibilidade**: Se o vídeo for curto (< 75s) ou a IA sugerir apenas 1 corte, o fluxo se mantém 100% igual ao atual.

---

## 📂 Arquivos Afetados

| Arquivo | Responsabilidade |
|---------|------------------|
| `manga_fx_engine.py` | Implementação das animações estilo Jitter (spring, mask slide, blur snap) e novos estilos visuais de mangá |
| `anime_fx_analyzer.py` | Curadoria inteligente expandida para novos feelings e momentos emocionais/dramáticos |
| `refiner_mastercut.py` | Prompt com suporte a múltiplas opções adaptativas, parser flexível e renderização de candidatos |
| `refiner_tab.py` | UI com abas/seletor de opções, roteiro dinâmico e botões de ação contextuais |
| `studio_tab.py` | Suporte e compatibilidade transparente aos novos efeitos de mangá |

---

## 🛠️ Fases de Implementação

- [x] **Fase 1**: Desenvolver as novas funções de animação Jitter e novos feelings em `manga_fx_engine.py` (Elastic spring bounce, masked slide-up, blur-in focus snap, e 6 novos feelings: `domain_dark`, `blade_stream`, `blood_ink`, `cyber_glitch`, `comic_halftone`, `emotional_tear`).
- [x] **Fase 2**: Atualizar o prompt e curadoria semântica em `anime_fx_analyzer.py` para suportar os novos estilos e tons emocionais.
- [x] **Fase 3**: Implementar em `refiner_mastercut.py` o suporte a múltiplas opções para vídeos longos (> 75s) adaptadas ao tom emocional (sem ordem rígida, suportando vídeos tristes, de ação ou mistos), parser universal `_extract_timeline_and_options`, e renderização multicandidata em `MastercutPipeline.process`.
- [x] **Fase 4**: Criar o seletor visual de opções na interface de `refiner_tab.py` (`self.options_frame`, botões segmentados com destaque visual, chaveamento dinâmico de `output_path`, estatísticas e roteiro da cena).
- [x] **Fase 5**: Testes de validação unitária e garantia de não-regressão (testes com sucesso, compilação de sintaxe limpa, retrocompatibilidade 100% preservada para clipes curtos <=75s).
- [x] **Fase 6**: Categorização de Temas / Tipos de Recorte Mangá no Studio (`Geral`, `Triste / Emocional`, `Romântica / Shoujo`, `Ação / Batalha`, `Animada / Comédia`, `Sombria / Seinen`, `Épica / Clímax Supremo`) + Novos Quadros Editoriais HQ e Feelings temáticos + Remoção da elipse/forma redonda transparente atrás dos quadros mangá.
