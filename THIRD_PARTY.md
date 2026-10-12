# Componentes e referências

O código Python deste projeto foi implementado independentemente. Não foi copiado código, fontes, ícones ou temas do projeto de voky1.

| Componente | Uso | Licença / origem |
| --- | --- | --- |
| voky1/sims4-translator | Inspiração da tabela, revisão e fluxo de tradução | Projeto de referência sob MIT; [repositório](https://github.com/voky1/sims4-translator) |
| Simple Ren'Py Tool v1.1 | Binário de extração/decompilação | `srtp_v1.1.zip` enviado pelo usuário; não contém licença explícita de redistribuição |
| PySide6 Essentials | Interface desktop Qt | LGPLv3/GPLv3/comercial; consulte a distribuição Qt for Python |
| Requests | Requisições HTTPS | Apache 2.0 |
| PyYAML | Leitura/escrita YAML | MIT |
| Ren'Py | Gerador e runtime externos | Consulte a licença da versão do jogo/SDK; o motor não é incluído |

O arquivo `renpy_revisor/resources/srtp_v1.1.zip` é a cópia integral do anexo, com SHA-256:

```text
165c11fb6e1819eb35694eaebe5045b525ace6fbbbf4460a279ceb1c3631e165
```

Seu `readme.txt` documenta os argumentos CLI usados pelo aplicativo. Os arquivos do pacote são tratados como documentação/dados da ferramenta; o programa não executa `install.bat`, `uninstall.bat`, não registra menus no Windows e não instala os tweaks do pacote. Apenas `srt.exe`, `libzstd.dll` e `readme.txt` são extraídos para a área de trabalho de cada projeto.

A licença deste projeto não concede direitos de redistribuição sobre o SRT. Antes de publicar uma distribuição que o inclua, confirme os termos com seu autor. O aplicativo também permite selecionar uma instalação externa de `srt.exe`, com `libzstd.dll` ao lado.
