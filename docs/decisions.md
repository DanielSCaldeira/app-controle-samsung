# Registro de Decisões Arquiteturais (ADRs)

## ADR-0001 — Kotlin + Jetpack Compose como linguagem e UI

**Status:** Accepted · 2026-06-01

**Contexto.** Precisamos de um app Android nativo, responsivo e de baixa latência para
controlar a TV. As opções incluíam Java, Kotlin nativo ou frameworks multiplataforma
(Flutter/React Native).

**Decisão.** Usar Kotlin com Jetpack Compose e Material 3 como stack de UI nativa.

**Consequências.** (+) Acesso direto a APIs de rede (WebSocket, multicast UDP, Wi-Fi),
melhor latência e ecossistema AndroidX (ViewModel, Flow, Room, Hilt). (+) Compose acelera
a construção de uma UI de controle rica. (−) Restringe a plataforma a Android (aceitável,
pois o goal é explicitamente Android).

**Alternativas.** *Flutter/React Native* — descartados: camadas de abstração adicionam
overhead em sockets/multicast e dificultam o acesso a APIs de rede de baixo nível.
*Java* — descartado por verbosidade e ausência de corrotinas idiomáticas.

---

## ADR-0002 — Persistência local com Room + cifragem de token

**Status:** Accepted · 2026-06-01

**Contexto.** Precisamos lembrar TVs pareadas e seus tokens de autorização entre sessões.
O token concede controle total da TV e é sensível. Não há requisito de sincronização
em nuvem (YAGNI).

**Decisão.** Persistir TVs conhecidas em um banco Room local; armazenar o token cifrado
via Jetpack Security (Tink/EncryptedSharedPreferences), nunca em texto plano.

**Consequências.** (+) Funciona offline, zero custo de backend, dados sob controle do
usuário. (+) Token protegido em repouso. (−) Sem backup/sincronização entre dispositivos
(re-pareamento necessário em outro aparelho — aceitável).

**Alternativas.** *Backend na nuvem* — descartado por custo, complexidade e por violar
o princípio de operação 100% LAN. *SharedPreferences puro* — descartado por não atender
ao requisito de cifragem do token e por falta de modelo relacional.

---

## ADR-0003 — Comunicação com a TV via WebSocket do protocolo Samsung Tizen

**Status:** Accepted · 2026-06-01

**Contexto.** Smart TVs Samsung modernas (4K, QLED, Crystal, Neo QLED, OLED) expõem uma
API de controle remoto sobre WebSocket (portas 8001/8002), com handshake de token e envio
de teclas (`KEY_*`) e lançamento de apps. É o canal usado por controles via app.

**Decisão.** Adotar WebSocket persistente (OkHttp) como transporte para comandos e
eventos, encapsulado em `RemoteSession`. Comandos são objetos `RemoteKey`/mensagens JSON
mapeadas para o protocolo Tizen em uma camada `protocol/` isolada.

**Consequências.** (+) Conexão full-duplex de baixa latência, recebe eventos de estado da
TV, padrão de fato para controle Samsung. (+) A camada `protocol/` isolada protege o resto
do app de mudanças no protocolo. (−) Protocolo não é oficialmente documentado/estável;
exige TLS auto-assinado na 8002 e tratamento de variações entre modelos.

**Alternativas.** *DLNA/UPnP puro* — descartado: cobre mídia, não o conjunto completo de
teclas de controle. *IR/HDMI-CEC* — descartado: o goal exige controle por Wi-Fi.
*REST polling* — descartado por latência e ausência de eventos push.

---

## ADR-0004 — Descoberta de TVs por SSDP/mDNS com fallback manual

**Status:** Accepted · 2026-06-01

**Contexto.** O usuário não deve digitar IPs. Precisamos localizar automaticamente TVs
Samsung na LAN, mas algumas redes bloqueiam multicast.

**Decisão.** Descoberta primária via SSDP (multicast UDP) e mDNS, validando candidatos
pelo endpoint REST `/api/v2/` da TV; oferecer entrada manual de IP como fallback.

**Consequências.** (+) Experiência sem configuração no caso comum. (+) Robusto em redes
restritivas via fallback. (−) Lógica de descoberta com múltiplos caminhos a manter e
testar.

**Alternativas.** *Apenas entrada manual de IP* — descartado por má UX. *Apenas SSDP* —
descartado por falhar em redes que bloqueiam multicast.

---

## ADR-0005 — Arquitetura em camadas MVVM com fluxo unidirecional

**Status:** Accepted · 2026-06-01

**Contexto.** Queremos componentes pequenos, testáveis e de baixo acoplamento, fáceis de
implementar em tarefas pequenas pelos roles `planner`/`coder`.

**Decisão.** Adotar MVVM com fluxo de estado unidirecional: UI (Compose) observa
`StateFlow` dos ViewModels; ViewModels delegam a um `CommandRepository`/`RemoteSession`;
injeção de dependências com Hilt.

**Consequências.** (+) Camadas substituíveis e testáveis (transporte mockável).
(+) Estado previsível e único por tela. (−) Boilerplate de ViewModels/DI inicial.

**Alternativas.** *UI acessando sockets diretamente* — descartado por acoplamento e
impossibilidade de teste. *Arquitetura sem DI* — descartado por dificultar a troca de
implementações em testes.

---

## ADR-0006 — Teclas de atalho de streaming como catálogo configurável

**Status:** Accepted · 2026-06-01

**Contexto.** O goal exige atalhos para Netflix, Prime Video e outros. IDs de apps Tizen
variam entre modelos/firmwares e novos serviços surgem.

**Decisão.** Modelar atalhos como um catálogo estático/configurável (`AppShortcut`) com
`launchApp(appId)` e fallback para navegação por teclas, em vez de hardcode na UI.

**Consequências.** (+) Adicionar/ajustar serviços sem mudar a UI; resiliente a variações
de modelo. (−) Necessário manter o catálogo atualizado.

**Alternativas.** *Hardcode dos atalhos na tela* — descartado por rigidez e duplicação.

---

## ADR-0007 — Contrato de fio versionado + pytest como runner de CI

**Status:** Accepted · 2026-06-02

**Contexto.** O protocolo Tizen não é oficialmente documentado e pode mudar entre
firmwares; precisamos detectar regressões no formato de fio. Além disso, o runner de
CI da fábrica é pytest, enquanto o código de produção é Kotlin (depende de `org.json`,
presente no Android mas ausente num JVM desktop).

**Decisão.** Congelar o formato de fio em um contrato golden versionado
(`tests/contracts/tizen_protocol_v2.json`) exercido por testes de contrato; manter
pytest como runner principal, compilando/executando o Kotlin real (com shim de
`org.json` quando preciso) e fazendo `skip` quando não há toolchain — complementado
pelos testes nativos `app/src/test` (unitários) e `app/src/androidTest` (Room + Compose).

**Consequências.** (+) Qualquer alteração no formato de fio quebra os testes de
propósito, forçando uma revisão consciente (nova versão `v3` em vez de editar o golden).
(+) CI roda em ambientes sem device. (−) Suíte de testes dupla (pytest + Gradle) a
manter; testes podem dar `skip` silencioso sem toolchain Kotlin.

**Alternativas.** *Só testes nativos Gradle* — descartado por não integrar ao runner
pytest da fábrica. *Asserts soltos sem golden* — descartado por não detectar mudanças
sutis de formato.

---

## ADR-0008 — Wake-on-LAN para ligar a TV desligada

**Status:** Accepted · 2026-06-02

**Contexto.** Com a TV totalmente desligada, o WebSocket de controle fica indisponível,
então o botão Power não a liga (risco já previsto na arquitetura §8).

**Decisão.** Quando um `PressKey(KEY_POWER)` não alcança uma conexão aberta, enviar um
"magic packet" Wake-on-LAN (UDP broadcast) para o MAC persistido da TV
(`KnownTv.macAddress`). O `WakeOnLan` separa a construção pura do pacote (`buildMagicPacket`,
testável) do envio UDP; quando o MAC é desconhecido, é no-op silencioso.

**Consequências.** (+) O botão Power liga a TV mesmo desligada, completando a paridade
com o controle físico. (+) Lógica pura testável isoladamente. (−) Depende de o MAC ter
sido capturado e de a TV/rede permitirem WoL (alguns ambientes bloqueiam broadcast).

**Alternativas.** *Não suportar ligar TV desligada* — descartado por quebrar a
expectativa de um controle completo. *Manter socket sempre aberto* — impossível com a
TV sem energia.
