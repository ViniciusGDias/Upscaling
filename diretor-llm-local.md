# Diretor IA — Motor LLM Local (Modo Opcional)

## Goal
Criar um modo **opcional e desligado por padrão** em que o Diretor IA roda num LLM local
(fine-tuned via destilação do Gemini), sem alterar em nada o fluxo atual.

## Princípios
- **Zero regressão:** Gemini → Groq → OpenRouter continua idêntico. Modo local só entra se ativado
  e, se falhar (JSON inválido, Ollama offline), cai automaticamente na cadeia atual.
- **Treino fora do app:** tudo de ML fica em `ml/` (não entra no build do .exe).
- **Branch dedicada:** `feature/director-local-llm`.

## Fase 1 — Coleta de dados (agora)
- [x] Criar branch `feature/director-local-llm` → Verify: `git branch --show-current`
- [x] Criar `dataset_logger.py`: append JSONL em `.cache/training/director.jsonl`
      (fora do `ai_hub`, imune ao TTL/LRU) → Verify: teste unitário grava/lê 1 registro
- [x] Em `director_ai.call_ai_text`: registrar provider+modelo que respondeu (variável de módulo,
      sem mudar assinatura) → Verify: chamadas existentes inalteradas
- [x] Em `analyze_episode` / `analyze_episode_reroll`: logar `{prompt, response, provider, model,
      mode, cut_mode, genre, duration, n_candidates, parse_ok}` só após sucesso → Verify: rodar 1 episódio, 1 linha no JSONL
- [x] Logger nunca lança exceção (try/except silencioso) → Verify: teste com disco read-only não quebra análise
- [x] Adicionar `.cache/training/` ao `.gitignore` (já coberto por `.cache/`)
- [x] Resgatar 34 amostras + 133 feedbacks do cache existente via `scripts/salvage_cache_director.py`

## Fase 2 — Sinal de feedback (concluído antecipadamente)
- [x] Em `director_tab.py`: ao cortar/exportar um candidato, logar evento `accepted` ligado ao
      episódio e título do corte → base para filtrar qualidade e, futuramente, DPO

## Fase 3 — Pipeline de treino (`ml/director/`)
- [ ] `build_dataset.py`: filtra (parse_ok, provider), dedup, split **por episódio** (train/val/test),
      aplica *prompt distillation* (prompt curto) → gera `train.jsonl` em formato chat
- [ ] `train_lora.py`: QLoRA com Unsloth — Qwen3-1.7B (baseline) e Qwen3-4B
- [ ] `evaluate.py`: JSON válido %, schema %, timestamps dentro da duração, ordem cronológica,
      duração por `cut_mode`, IoU temporal vs. cortes do Gemini
- [ ] Exportar GGUF Q4_K_M → registrar no Ollama (`Modelfile`)

## Fase 4 — Integração opcional
- [ ] `settings_manager`: `director_engine = "cloud" | "local"` (default `cloud`)
- [ ] `call_ai_text`: Tier 0 local (Ollama, `format=json`) somente se `local`; fallback automático
- [ ] Toggle "Motor Local (Experimental)" na aba Configurações

## Done When
- [ ] Com o modo desligado, o app se comporta byte-a-byte igual ao atual
- [ ] Modelo local ≥ 95% JSON válido e IoU médio aceitável no test set
- [ ] Modo local roda nos 8 GB sem conflitar com Whisper/Real-CUGAN (keep_alive=0)

## Notes
- RTX 5060 (Blackwell, sm_120) exige PyTorch com CUDA ≥ 12.8.
- Meta de dados: ~300 exemplos para o 1º experimento; 1.000+ para resultado sólido.
- Termos do Gemini restringem usar saídas para criar modelos concorrentes — uso pessoal/local é
  zona cinza; alternativa: usar saídas do Groq (gpt-oss-120b, Apache 2.0) como professor.
