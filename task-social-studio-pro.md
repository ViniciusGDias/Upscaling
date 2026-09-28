# Plano de Implementação: Batch, Inteligência Social & Studio Pro

## Objetivo
Implementar as 8 melhorias aprovadas pelo usuário para o ecossistema Urahara:
1. **Score Viral Visual (0-100)**: Medidor visual com barra de progresso, status cromático e diagnóstico algorítmico.
2. **Detector de Hook Fraco**: Identificação nos primeiros 3s com alertas visuais e gancho sugerido pela IA.
3. **A/B de Títulos Interativo**: Cards clicáveis com as 3 melhores variações de título, clique para ativar/copiar e destaque visual.
4. **Geração Multilíngue (PT / EN / ES)**: Seletor de idioma em tempo real para prompts do Gemini.
5. **Templates de Legenda Salvos**: Presets de copywriting (Storytelling, Suspense, Hype, CTA Agressivo) com preenchimento instantâneo.
6. **Notificação Toast Nativa do Windows**: Aviso sonoro/visual quando longas análises e lotes forem concluídos.
7. **Mini-Player In-App de Prévia**: Player embutido compacto para inspecionar o vídeo diretamente na interface.
8. **Aba Dedicada 'Batch & Histórico'**:
   - Modo Repurpose em Lote para pastas inteiras com exportação CSV.
   - Explorador de Histórico de análises com busca em tempo real e reabertura sem custo de tokens.

---

## Fases de Execução

### Fase 1: Módulos de Suporte & Inteligência
- `windows_notifier.py`: Disparador de notificações nativas Windows (PowerShell Toast assíncrono).
- `social_analyzer.py`:
  - Adicionar suporte a Espanhol (`ES`) junto com `PT` e `EN`.
  - Refinar cálculo do `viral_score` e diagnóstico de hook.
  - Adicionar templates de copy predefinidos.

### Fase 2: Componentes Visuais Reutilizáveis
- `video_preview_player.py`: Mini-player in-app embutido com suporte a Play/Pause, scrubber e extração de frames via OpenCV/PIL.
- Cards de Título A/B e Gauge de Score Viral com estilos CustomTkinter Obsidian & Emerald.

### Fase 3: Atualização das Abas de Análise
- `yt_shorts_tab.py`:
  - Integrar seletor Multilíngue (PT / EN / ES).
  - Integrar seletor de Templates de Copy.
  - Integrar Cards de Títulos A/B.
  - Integrar Medidor de Score Viral e Badge de Hook Fraco/Forte.
  - Integrar Mini-Player In-App.
  - Integrar Notificação Toast ao finalizar.
- `instagram_tab.py`:
  - Atualizações análogas para o Instagram Reels.

### Fase 4: Nova Aba 'Batch & Histórico'
- Criar `batch_history_tab.py` com:
  - Fila de processamento em lote com thread worker segura e barra de progresso.
  - Exportação direta para CSV / JSON.
  - Painel de Histórico integrado com `ai_cache_hub.py` e busca dinâmica.
- Registrar em `sidebar_navigation.py` e `app.py`.
- Atualizar `build_exe.py` para incluir os novos arquivos.

### Fase 5: Validação & Build
- Validar sintaxe com `python -m py_compile`.
- Testar inicialização e sincronizar com `dist/Urahara`.
