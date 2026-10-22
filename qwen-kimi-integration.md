# Integração Multi-Modelo: Ollama Local (Qwen 2.5 7B) + Qwen-Max + Kimi

## Goal
Adicionar suporte opcional aos modelos **Ollama Local (Qwen 2.5 7B)**, **Qwen-Max (OpenRouter)** e **Kimi (Moonshot / OpenRouter)** no Diretor IA e Configurações, mantendo o Gemini como padrão absoluto e zero regressão no app.

## Tasks
- [x] Iniciar download do `qwen2.5:7b` via Ollama em segundo plano → Verify: `ollama list` lista qwen2.5:7b (Download de 4.7 GB concluído com sucesso)
- [x] Atualizar `settings_manager.py`: adicionar suporte a `DIRECTOR_ENGINE` e opções de modelos (`gemini`, `ollama_local`, `qwen_max`, `kimi`) → Verify: `load_app_settings()` carrega os valores
- [x] Atualizar `director_ai.py`: implementar chamadas para Ollama local (`/api/chat` com `format="json"`, `keep_alive=0` para liberar VRAM da RTX 5060) e rotas OpenRouter para Qwen-Max e Kimi → Verify: chamadas com fallback resiliente
- [x] Atualizar `settings_tab.py`: adicionar seletor de "Motor Principal do Diretor IA" e status do Ollama → Verify: UI exibe o seletor e salva no `.env`
- [x] Atualizar `director_tab.py`: adicionar seletor rápido de motor no topo da aba Diretor IA → Verify: permite alternar o motor para a análise atual
- [x] Testar integração com teste unitário e chamada de validação → Verify: `python -m unittest tests/test_multi_engine.py` (4 testes OK)

## Done When
- [x] Gemini continua sendo o padrão se o usuário não alterar nada
- [x] Se o usuário selecionar Ollama local, a requisição vai para `http://localhost:11434`
- [x] Se Ollama falhar ou estiver desligado, faz fallback automático para a cadeia existente
- [x] Qwen-Max e Kimi funcionam via OpenRouter se selecionados
