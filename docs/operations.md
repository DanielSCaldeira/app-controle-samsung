# Guia de operação — build, testes e execução

Este documento é o ponto de entrada prático para quem precisa **compilar, testar,
instalar e diagnosticar** o app de controle remoto Samsung. A visão de arquitetura
está em [`architecture.md`](architecture.md); as decisões em [`decisions.md`](decisions.md).

## 1. Pré-requisitos

- **JDK 17** no `PATH` (`java -version`).
- **Android SDK** + `adb` no `PATH` (para instalar/depurar em device/emulador).
- **GNU Make** (opcional, mas os atalhos abaixo dependem dele).
- **Python 3.12** com `pytest` (para a suíte de testes da fábrica em `tests/`).
- O wrapper do Gradle já está versionado (`gradlew` / `gradlew.bat`), não é preciso
  instalar Gradle global.

Configurações locais ficam em `local.properties` (caminho do SDK) e
`gradle.properties` — não versione segredos.

## 2. Comandos do dia a dia (Makefile)

`make help` lista tudo. Os mais usados:

| Comando | O que faz |
|---------|-----------|
| `make doctor` | Checa Java, `adb` e dispositivos conectados |
| `make build` | Compila e roda as verificações do módulo `app` |
| `make assemble-debug` | Gera o APK debug |
| `make install-debug` (ou `make install`) | Compila e instala no device/emulador conectado |
| `make test` | Testes unitários JVM de todas as variantes |
| `make test-debug` | Testes unitários da variante debug |
| `make android-test` | Testes instrumentados (Room + Compose UI) em device conectado |
| `make connected-check` | Todas as verificações em device conectado |
| `make lint` | Lint Android |
| `make app-start` / `make app-stop` | Abre / força parada do app no device |
| `make adb-logcat` | Logs em tempo real |

> No Windows o `Makefile` chama `./gradlew.bat`. Sem Make, use os mesmos alvos Gradle
> diretamente, ex.: `./gradlew.bat :app:installDebug`.

## 3. Suítes de testes

São duas, complementares (ver `architecture.md` §13):

1. **pytest (`tests/`)** — runner de CI da fábrica. Rode com `pytest` na raiz. Quando
   há toolchain Kotlin nas caches do Gradle, vários testes compilam e executam o
   código Kotlin real; caso contrário fazem checagem estrutural e dão `skip` (não
   falham). O contrato de fio do protocolo está em
   `tests/contracts/tizen_protocol_v2.json`.
2. **Testes nativos Android** — `make test` (unitários JVM, transporte mockado via
   `CommandTransport`) e `make android-test` (instrumentados: `KnownTvDaoTest`,
   Compose UI com `RemoteTestTags`, acessibilidade/TalkBack).

### Verificação end-to-end de build e inicialização

`tests/test_app_build_and_launch_e2e.py` é a checagem de fumaça do app inteiro:

- **Rápida (sem device):** confirma que a única activity exportada é a `MainActivity`
  LAUNCHER e que o host de navegação parte de `Screen.Discovery`.
- **Lenta (`-m slow`):** roda `./gradlew :app:build` exigindo `BUILD SUCCESSFUL`; e,
  havendo device/emulador (`adb`) conectado, instala via `:app:installDebug`, lança o
  app, confirma que a `MainActivity` é a activity resumida, que o processo segue vivo,
  varre o logcat por `FATAL EXCEPTION` e valida via `uiautomator` que a tela de
  descoberta (`discovery_title`) foi renderizada. Sem device, esses passos dão `skip`
  (não falham).

> Rode os testes lentos explicitamente com `pytest -m slow`; o build autoritativo pode
> levar minutos no primeiro run (download de dependências do Gradle).

## 4. Usando o app (fluxo do usuário)

1. **Conecte o telefone à mesma rede Wi-Fi da TV.** O app opera 100% na LAN.
2. **Descoberta.** Ao abrir, a tela de descoberta lista as TVs Samsung encontradas via
   SSDP/mDNS. Se a rede bloqueia multicast, use a **entrada manual de IP**.
3. **Pareamento.** Ao selecionar uma TV nova, a própria TV exibe um prompt de
   autorização; aceite nela. O token retornado é salvo **cifrado** (Android Keystore)
   e reusado nas próximas conexões.
4. **Controle.** A `RemoteScreen` oferece D-pad, OK/Return/Home/Menu, volume/mute,
   canais, teclado numérico, transporte de mídia (play/pause/stop/rew/ff), entrada de
   texto e atalhos para Netflix, Prime Video, Disney+ e YouTube.
5. **Ligar a TV.** O botão Power liga via Wake-on-LAN quando a TV está totalmente
   desligada (requer o MAC conhecido, capturado na descoberta/pareamento).

## 5. Compatibilidade

- **Android:** 8.0 (API 26) ou superior.
- **TVs:** Samsung Tizen com WebSocket de controle (portas 8001/8002), linhas 4K,
  QLED, Crystal, Neo QLED e OLED (~2016+).
- **Permissões:** apenas rede (`INTERNET`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE`,
  `CHANGE_WIFI_MULTICAST_STATE`). Sem localização, armazenamento ou telemetria.

## 6. Troubleshooting

| Sintoma | Causa provável | O que fazer |
|---------|----------------|-------------|
| Nenhuma TV aparece na descoberta | Multicast (SSDP/mDNS) bloqueado pela rede; telefone em outra VLAN/Wi-Fi de visitantes | Use entrada manual de IP; garanta mesma rede; verifique `CHANGE_WIFI_MULTICAST_STATE` |
| Pareamento falha / não aparece prompt na TV | Token expirado/revogado; TLS auto-assinado rejeitado | Re-parear; o `LanTrustManager` aceita o cert da TV só na sessão LAN |
| Comandos param de funcionar de repente | Queda de Wi-Fi → reconexão em curso | Observe o estado (`Reconnecting`); volta sozinho, ou aparece `Error` ao esgotar tentativas |
| TV "sumiu" depois de um tempo | IP mudou por DHCP | `TvReconciler` re-descobre pelo device id e atualiza o IP; reabra a TV se necessário |
| Botão Power não liga a TV | MAC desconhecido (sem Wake-on-LAN) | Garanta que a TV foi descoberta/pareada ao menos uma vez para capturar o MAC |
| Atalho de app não abre o serviço | ID Tizen difere no modelo/firmware | Ajuste/estenda `AppShortcutCatalog`; há fallback configurável |

Para depuração detalhada, use `make adb-logcat` com o app aberto.
