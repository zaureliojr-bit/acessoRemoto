# Acesso Remoto (rede doméstica)

Programa de acesso remoto, no estilo AnyDesk, para uso dentro de uma rede
doméstica (LAN). É um **único aplicativo** (`app.py`) que faz os dois
papéis ao mesmo tempo:

- Ao abrir, já fica pronto para **ser acessado**: mostra seu IP na rede
  local e uma senha gerada automaticamente (renovável a qualquer momento
  com um clique).
- Também tem um campo para você **acessar outro computador**: basta
  informar o IP e a senha exibidos na tela da outra máquina (que também
  precisa estar com o app aberto).

Por baixo dos panos, a comunicação usa duas conexões TCP simples: uma
para o vídeo (frames JPEG da tela) e outra para os comandos de controle
(mouse/teclado, em JSON). O acesso é protegido por senha.

## Instalação (a partir do código-fonte)

Em **ambas** as máquinas:

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

No Linux, o `pynput` precisa de um servidor X11 (não funciona em Wayland
puro) para controlar mouse/teclado.

## Uso

Nas duas máquinas:

```bash
python app.py
```

Na janela que abrir:

- Em **"Permitir que me acessem"**, veja seu IP e a senha gerada — passe
  essas informações (por WhatsApp, por exemplo) para quem for te acessar.
- Em **"Acessar outro computador"**, digite (ou escolha na lista de IPs
  já usados) o IP e a senha mostrados na tela da outra máquina, e clique
  em **Conectar**. Uma nova janela abre com a tela remota; mova o mouse,
  clique e digite dentro dela para controlar a outra máquina.
- Todo IP que você conseguir conectar fica salvo num histórico local (no
  seu usuário do Windows, não é compartilhado com ninguém), disponível
  no campo de IP na próxima vez. Use **"Limpar histórico"** para apagar
  essa lista.

## Versão instalável (Windows, .exe)

Não é necessário ter Python instalado nas máquinas Windows para usar o
programa. A cada push no branch `main`, o GitHub Actions gera
automaticamente `AcessoRemoto.exe`.

Para baixar:

1. No GitHub, abra a aba **Actions** do repositório.
2. Clique na execução mais recente do workflow **Build executaveis Windows**.
3. Na seção **Artifacts**, baixe `acesso-remoto-windows` (um `.zip` com
   o `AcessoRemoto.exe`).

Basta dar duplo clique no `AcessoRemoto.exe` em cada máquina — a
interface é a mesma descrita na seção "Uso" acima.

O Windows Defender/SmartScreen pode alertar por ser um executável não
assinado digitalmente — isso é esperado para um projeto pessoal sem
certificado de assinatura de código; escolha "Executar assim mesmo". O
Firewall do Windows também pode pedir permissão de rede na primeira
execução — permita o acesso para redes privadas/domésticas.

### Gerar o .exe manualmente (opcional)

Em uma máquina Windows com Python instalado:

```
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --noconsole --name AcessoRemoto app.py
```

O `.exe` fica em `dist/`.

### Uso avançado via linha de comando (opcional)

Os scripts `server.py` e `client.py` continuam disponíveis separadamente
para quem preferir rodar cada papel manualmente (ex.: servidor sem
interface gráfica numa máquina "headless") ou definir uma senha fixa em
vez da gerada automaticamente:

```bash
python server.py --password "escolha-uma-senha-forte"
python client.py 192.168.0.42 --password "escolha-uma-senha-forte"
```

Opções úteis do `server.py`: `--monitor N` (monitor a capturar),
`--quality N` (qualidade JPEG 1-100), `--fps N`, `--video-port` /
`--control-port`.

## Avisos de segurança

- **Feito para uso em rede local confiável.** O tráfego de vídeo e
  controle **não é criptografado**. Não exponha as portas 5000/5001 à
  internet (não faça port-forward no roteador).
- A senha é comparada por hash SHA-256 na autenticação, mas a conexão em
  si não usa TLS — qualquer pessoa na mesma rede local poderia, em
  teoria, capturar o tráfego. Para uso doméstico numa rede Wi-Fi/cabo
  confiável isso é geralmente aceitável, mas não é adequado para redes
  públicas ou uso pela internet sem antes adicionar criptografia (ex.:
  túnel TLS/SSH ou VPN).
- A senha gerada automaticamente muda a cada abertura do programa (ou ao
  clicar em "Gerar nova senha"), o que já reduz bastante o risco de
  reuso — mesmo assim, evite deixar o app aberto e "ouvindo" sem
  necessidade.

## Limitações conhecidas / próximos passos

- Sem criptografia da conexão (TLS) — recomendado como próxima melhoria.
- Sem suporte a múltiplos clientes simultâneos por servidor.
- Sem transferência de arquivos (pode ser adicionada depois).
- No Linux/Wayland, controle remoto de mouse/teclado não funciona
  (limitação do `pynput`); funciona normalmente em X11 e Windows.
