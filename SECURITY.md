# Segurança — DrogaLink Remote

Estado: experimental; não aprovado para uso em produção.

## Verificações estáticas

Execute `python -m unittest discover -s tests -v`. As verificações não iniciam conexões nem capturam a tela. Elas verificam a presença das proteções no código, não demonstram segurança operacional.

## Critérios de aceitação antes da distribuição

- Recebimento desativado por padrão e ativação explícita no dispositivo local.
- Indicador visível de acesso e botão local de encerramento.
- Verificação manual no Windows de que o encerramento interrompe todo o acesso.
- Revisão independente de autenticação e proteção do tráfego; preferir soluções de suporte consolidadas.
- Consentimento por sessão, a ser concluído após os demais itens.
- Registro de eventos sem senhas, imagens, teclas ou dados pessoais.
- Distribuição assinada e validação do instalável.

Não exponha o aplicativo à internet, nem utilize dados de clientes em testes. Não publique uma nova versão para produção antes de concluir a validação.
