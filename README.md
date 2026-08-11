# Acesso Remoto (rede doméstica)

Programa simples de acesso remoto, no estilo AnyDesk, para uso dentro de
uma rede doméstica (LAN). Arquitetura cliente-servidor:

- `server.py` roda na máquina que será **controlada** (captura a tela e
  aplica os comandos de mouse/teclado recebidos).
- `client.py` roda na máquina que vai **controlar** a outra (mostra a
  tela remota numa janela e envia os eventos de mouse/teclado).

A comunicação usa duas conexões TCP simples: uma para o vídeo (frames
JPEG) e outra para os comandos de controle (JSON). O acesso é protegido
por senha compartilhada.

## Instalação

Em **ambas** as máquinas:

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

No Linux, o `pynput` precisa de um servidor X11 (não funciona em Wayland
puro) para controlar mouse/teclado.

## Uso

Na máquina que será acessada (servidor):

```bash
python server.py --password "escolha-uma-senha-forte"
```

Na máquina que vai acessar (cliente), use o IP local do servidor
(ex.: `192.168.0.42`, visível com `ipconfig`/`ifconfig`/`ip a`):

```bash
python client.py 192.168.0.42 --password "escolha-uma-senha-forte"
```

Uma janela abre mostrando a tela remota. Mova o mouse, clique e digite
dentro da janela para controlar a outra máquina.

### Opções úteis do servidor

- `--monitor N`: escolhe qual monitor capturar quando há mais de um.
- `--quality N`: qualidade JPEG (1-100), menor = mais rápido, menos nítido.
- `--fps N`: quadros por segundo enviados (padrão 15).
- `--video-port` / `--control-port`: portas TCP (padrão 5000 e 5001).

## Versão instalável (Windows, .exe)

Não é necessário ter Python instalado nas máquinas Windows para usar o
programa. A cada push no branch `main`, o GitHub Actions gera
automaticamente dois executáveis:

- `AcessoRemoto-Servidor.exe`
- `AcessoRemoto-Cliente.exe`

Para baixar:

1. No GitHub, abra a aba **Actions** do repositório.
2. Clique na execução mais recente do workflow **Build executaveis Windows**.
3. Na seção **Artifacts**, baixe `acesso-remoto-windows` (um `.zip` com
   os dois `.exe`).

Uso é o mesmo de antes, só que via linha de comando com o `.exe` em vez
de `python arquivo.py`:

```
AcessoRemoto-Servidor.exe --password "escolha-uma-senha-forte"
AcessoRemoto-Cliente.exe 192.168.0.42 --password "escolha-uma-senha-forte"
```

O Windows Defender/SmartScreen pode alertar por ser um executável não
assinado digitalmente — isso é esperado para um projeto pessoal sem
certificado de assinatura de código; escolha "Executar assim mesmo".

### Gerar o .exe manualmente (opcional)

Em uma máquina Windows com Python instalado:

```
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --name AcessoRemoto-Servidor server.py
pyinstaller --onefile --noconsole --name AcessoRemoto-Cliente client.py
```

Os `.exe` ficam em `dist/`.

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
- Use uma senha forte e não a reutilize de outras contas.

## Limitações conhecidas / próximos passos

- Sem criptografia da conexão (TLS) — recomendado como próxima melhoria.
- Sem suporte a múltiplos clientes simultâneos por servidor.
- Sem transferência de arquivos (pode ser adicionada depois).
- No Linux/Wayland, controle remoto de mouse/teclado não funciona
  (limitação do `pynput`); funciona normalmente em X11 e Windows.
- A janela do cliente mostra a imagem no tamanho nativo da tela remota;
  se as resoluções forem muito diferentes, pode não caber na tela.
