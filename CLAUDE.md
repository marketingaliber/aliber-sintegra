# Aliber SINTEGRA

Gera o SINTEGRA (Convênio ICMS 57/95) direto do banco do PDV+ (que a Aliber chama de "Aliber Sistema")
e envia à contabilidade. Python + tkinter; instalador NSIS em `instalador/`. O dono do projeto não
programa: explique em português simples, com passo a passo, e entregue o resultado pronto.

## Versões e troca de versão
- Sem aviso de versão nova (mesmo modelo do Aliber Print). O técnico troca em Configurações >
  Escolher versão, com a senha do técnico (a mesma do Aliber Print; hash PBKDF2 em `versoes.py`).
- As versões publicadas são os arquivos `versoes/Instalar-AliberSintegra-X.Y.exe` deste repositório
  (público) e as notas `versoes/NOTAS-X.Y.md`. O app lista pela API do GitHub, baixa, confere o hash
  e roda o instalador com /S; o instalador reabre o programa no fim.
- Para publicar uma versão:
  1. Aumentar `VERSAO` em `app.py`, `VERSAO`/`VIProductVersion` em `instalador/instalador.nsi`,
     o texto do `GERAR_EXE.bat`, o LEIA-ME e o histórico do README.
  2. `makensis instalador/instalador.nsi` e mover o .exe gerado para `versoes/`.
  3. Escrever `versoes/NOTAS-X.Y.md` (português, para o técnico).
  4. Commit e push na main. Se o repositório virar privado, a troca de versão para de funcionar.
- Arquivo novo de código precisa entrar no `File` do instalador e no `--hidden-import` do GERAR_EXE.bat.

## Regras
- Nunca subir dados de clientes (bancos .db, SINTEGRA .TXT, XMLs, planilhas).
- Antes de publicar, regenerar o SINTEGRA de 09/2026 da Ubá Utilidades e conferir que continua
  idêntico ao validado (quando o gerador não mudou de propósito).
- Advertências conhecidas e aceitas do validador: "Série inválida" no registro 61 (série numérica da
  NFC-e; o manual só prevê letras) e "Base de cálculo do ICMS" no 61R (Simples Nacional, sem ICMS).
