# Validação desta implementação

Ambiente: Debian 13, Python 3.12, PySide6 Essentials 6.12.0. Validação em 12/10/2026.

| Verificação | Resultado observado |
| --- | --- |
| Instalação editável com dependências de desenvolvimento | Concluída |
| Repetição do script de instalação na nuvem | Concluída |
| `python -m pytest -q` com Qt offscreen | **32 aprovados, 2 ignorados** |
| `python -m pip check` | Nenhuma dependência incompatível |
| Interface Qt criada, mostrada e manipulada sem tela | Concluída; captura em `docs/interface.png` |
| Edição, revisão, busca e reabertura de projeto | Verificadas pelos testes Qt |
| Exportação, backup, conflitos e restauração em falhas | Verificados com fixtures locais |
| Fila de até 50 strings e tratamento de falhas Google | Verificados com respostas HTTP simuladas |
| Ferramenta SRT incluída no pacote | ZIP conferido pelo SHA-256 do anexo; `.exe` e DLL extraídos em teste |
| SRT real em um arquivo RPA | **Não executado:** sem Windows/Wine |
| Jogo compilado → RPA → SRT → motor Ren'Py → tradução no runtime | **Não executado:** sem Windows/Wine e sem SDK disponível |
| Requisição real ao Google | **Bloqueada:** proxy respondeu `403 Forbidden` ao túnel HTTPS |
| Download do SDK pelo site oficial | **Bloqueado:** proxy respondeu `403 Forbidden` ao túnel HTTPS |
| Build de uma distribuição Windows `.exe` | **Não executado:** exige ambiente Windows |

Os dois testes nativos em `tests/test_native_integration.py` ficam disponíveis para a validação no Windows/SDK. Os testes simulados não demonstram compatibilidade da ferramenta binária com jogos reais.

O rascunho do ambiente contém `install_script`, `start_skill` e acréscimos de rede para `translate.google.com`, `www.renpy.org` e `dl.renpy.org`. Esse salvamento não aplica a rede à máquina atual nem publica o ambiente. Revise/salve nas configurações e publique para ativar a configuração preparada. A restauração em uma nova tarefa ainda não foi verificada.
