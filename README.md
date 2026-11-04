# Aliber SINTEGRA

Gera o arquivo SINTEGRA (Convênio ICMS 57/95) direto do banco do PDV+ e envia para a contabilidade
o SINTEGRA, os XMLs de entrada e saída e um relatório Excel de entradas e saídas.

Versão atual: **2.3**

## Download

**[Baixar Instalar-AliberSintegra-2.3.exe](https://github.com/marketingaliber/aliber-sintegra/raw/main/versoes/Instalar-AliberSintegra-2.3.exe)**

Na primeira instalação é preciso internet (o instalador baixa o Python oficial do python.org). Versões
anteriores ficam na pasta `versoes/`.

## Funcionalidades

- **Botão "Gerar SINTEGRA"**: escolhe o mês, gera o SINTEGRA, o relatório Excel e os zips de XML, confere os
  totais com o banco do PDV+ e envia à contabilidade (mês encerrado: envia direto; mês em andamento: pergunta e
  envia como PARCIAL).
- **Envio automático**: a partir do dia 1º, ao ligar o computador, gera o mês anterior, copia para a Área de
  Trabalho e envia (Gmail do cliente, com senha de app).
- **Simular envio automático**: testa a rotina do dia 1º sem mexer no relógio do Windows.
- Lê uma cópia do banco do PDV+ (`C:\PDV+\.dart_tool\sqflite_common_ffi\databases\navi_db.db`); nunca grava nele.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `app.py` | Tela principal, configurações, envio manual e simulação |
| `automatico.py` | Rotina do dia 1º, início com o Windows, avisos na tela |
| `motor_pdv.py` | Lê o banco do PDV+, extrai os XMLs, monta os zips e a conferência |
| `gerar_sintegra.py` | Gerador do arquivo SINTEGRA (registros 10, 11, 50, 53, 54, 61, 61R, 75, 88, 90) |
| `relatorio_excel.py` | Relatório Excel de entradas e saídas |
| `envio.py` | Envio pelo Gmail e proteção da senha (DPAPI do Windows) |
| `GERAR_EXE.bat` | Gera o `AliberSintegra.exe` (PyInstaller) num Windows com Python |
| `instalador/` | Script NSIS do instalador `Instalar-AliberSintegra-X.Y.exe` e pacotes offline (openpyxl) |

## Como gerar

- **.exe único**: no Windows, com Python instalado, dois cliques em `GERAR_EXE.bat`.
- **Instalador**: `makensis instalador/instalador.nsi` (gera `instalador/Instalar-AliberSintegra-2.3.exe`).

Instruções de uso completas em `LEIA-ME.txt`.

## Histórico

- **2.3**: registro 11 com endereço sem número (ex.: rodovia) saía com número 00000 e complemento vazio e era
  rejeitado pelo validador; agora o complemento sai como "SN".
- **2.2**: botão "Gerar SINTEGRA" também envia à contabilidade; envio PARCIAL para mês em andamento; instalador.
- **2.1**: simulação do envio automático.
- **2.0**: envio por e-mail, rotina automática do dia 1º, relatório Excel, zips de XML.
- **1.0**: geração do SINTEGRA direto do banco do PDV+, com conferência.

Nenhum dado de cliente (bancos .db, arquivos SINTEGRA, XMLs) deve ser enviado para este repositório.
