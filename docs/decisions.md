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

---

## ADR-0009 — Navegação single-activity com estado selado (Route/Screen)

**Status:** Accepted · 2026-06-02

**Contexto.** O fluxo do app é linear e fechado: Discovery → Pairing → Remote, onde a
TV escolhida e o token de pareamento precisam ser carregados de uma tela para a
próxima. Era preciso ligar essas três telas no `MainActivity` sem acoplar a UI a um
canal lateral de estado e mantendo as telas testáveis isoladamente.

**Decisão.** Adotar host **single-activity** em Compose: o destino atual é uma
`sealed interface Screen` (`Discovery`, `Pairing(tv)`, `Remote(tv, token)`) guardada em
`remember { mutableStateOf<Screen> }`, partindo de `Screen.Discovery`. A TV e o token
viajam dentro do próprio estado de navegação. Cada tela segue o padrão **Route/Screen**:
um `*Route` stateful (coleta o `StateFlow` do ViewModel via Hilt, expõe callbacks) que
delega a um `*Screen` stateless. A dependência `navigation-compose` fica disponível no
catálogo para evolução futura do grafo.

**Consequências.** (+) Estado de navegação tipado e explícito; argumentos (TV/token)
viajam type-safe sem canal lateral. (+) `*Screen` puros são testáveis em Compose UI
tests; a inicialização ponto-a-ponta é coberta pela verificação e2e. (−) Um host de
estado selado feito à mão não traz back stack/deep links — aceitável para o fluxo linear
atual; migrar para `NavHost` se o grafo crescer.

**Alternativas.** *`NavHost`/rotas string desde já* — adiável: overhead de
serialização de argumentos e rotas para um fluxo de três telas. *Estado em um ViewModel
de escopo de activity* — descartado por ser menos explícito que o `Screen` selado e por
acoplar navegação a um ViewModel compartilhado.

## ADR-0010 — Lançar apps e enviar texto via REST (`/api/v2/`) em Tizen 2020+

**Status:** Accepted · 2026-06-02

**Contexto.** Bug reportado em campo (TV Samsung 2020+): as teclas do controle
(D-pad, volume, power, mídia) funcionam, mas os **botões de apps de streaming não
abrem** os apps e a **busca por texto não digita** na TV. Diagnóstico: o formato dos
frames está correto e idêntico à biblioteca de referência (`samsung-tv-ws-api`), mas
o firmware Tizen 2020+ **honra `SendRemoteKey` e ignora silenciosamente
`ed.apps.launch` e `SendInputString`** pelo WebSocket de controle. Como o transporte
é o mesmo para todos os frames (ADR-0003), o sintoma é exatamente "teclas sim, app e
texto não".

**Decisão.** Manter o WebSocket para teclas, mas rotear **launch de app e entrada de
texto pelo plano REST** da TV (`http://<ip>:8001/api/v2/`, o mesmo host/porta já
usado por `RestTvCandidateValidator` na descoberta):

- `launchApp(appId)` → `POST /api/v2/applications/{appId}` (alta confiança; método
  documentado e usado por integrações maduras).
- `sendText(text)` → `POST /api/v2/remoteControl/imeInput/{base64}?token={token}`
  (best-effort; entrada de texto é limitada por firmware em sets recentes).

Implementado no próprio `RemoteSession` (OkHttp inline, reaproveitando via DI o client
LAN de timeout curto da descoberta — `@DiscoveryHttpClient`). `RemoteSession` lembra
`host`/`token` do alvo de `connect()` e sobrescreve `launchApp`/`sendText` do
`CommandTransport` — que agora recebe o **frame WebSocket de fallback pronto** (construído
por `CommandRepository` via `TizenProtocol`), mantendo a costura livre do protocolo:
tenta REST e **cai de volta para o frame WebSocket** se o REST falhar ou o host/cliente
for desconhecido. O REST é independente do socket de controle, então um launch funciona
mesmo durante reconexão.

**Consequências.** (+) Apps voltam a abrir em TVs 2020+; texto passa a ter um caminho
que funciona em parte dos sets. (+) Fallback preserva o comportamento antigo para
firmware mais velho e para os fakes de teste (o default do `CommandTransport` continua
emitindo os frames WebSocket). (+) Cobertura JVM: `RemoteSessionRestRoutingTest` valida,
via MockWebServer, que launch/texto batem nos endpoints REST corretos pelo caminho real
(`CommandRepository` → `RemoteSession`). (−) A
entrada de texto continua dependente de firmware — não há método programático 100%
confiável em Tizen 2020+; o usuário pode precisar usar o teclado on-screen via D-pad.
(−) Mais uma porta/plano de rede a manter (8001 HTTP além do 8002 WSS).

**Alternativas.** *Manter só o WebSocket* — descartado: é a causa do bug. *Codificar o
texto char-a-char via teclas* — frágil e lento, sem garantia de foco. *Remover o campo
de texto* — pioraria a UX sem necessidade, já que o REST IME funciona em parte dos sets.

## ADR-0011 — Descoberta de apps instalados em runtime (`ed.installedApp.get`)

**Status:** Accepted · 2026-06-03

**Contexto.** O catálogo de atalhos usava appIds fixos, mas eles **variam por
modelo/região/firmware** — o appId do Netflix antigo (`11101200001`) dá 404 na TV 2024
testada, enquanto `3201907018807` abre (ver ADR-0010). Manter IDs fixos é frágil: cada
TV pode ter IDs diferentes, e o usuário pediu que o app "descubra e se adapte" a cada TV.

**Decisão.** Descobrir os apps **em runtime** pela conexão WebSocket de controle já
aberta: ao abrir o socket, `RemoteSession` envia `ms.channel.emit` /
`ed.installedApp.get`; a TV responde com a lista sob `data.data` (cada item com `appId`,
`name`, `app_type`, `icon`). O parse fica isolado em `TizenProtocol.parseInstalledApps`,
e a lista é exposta como `RemoteSession.installedApps: StateFlow<List<InstalledApp>>`
(reexposta pelo `RemoteViewModel`), limpa a cada `connect()`. Na UI:

- os **atalhos curados** (Favoritos) resolvem o appId real pela lista descoberta
  (match por id, depois por nome — `resolveAppId`), caindo no id fixo do catálogo como
  reserva enquanto a descoberta não chega;
- abaixo, uma seção **"Todos os apps da TV"** lista todos os apps instalados, cada um
  lançado pelo seu próprio `appId` (sempre correto para aquele aparelho);
- o usuário pode **fixar** qualquer app da lista na home (estrela em cada tile),
  formando a seção **"Meus apps"**. A escolha é persistida por `FavoriteAppsStore`
  (SharedPreferences via `KeyValueStore`, serializada em JSON) e sobrevive a reinícios.

**Consequências.** (+) O remoto se adapta a qualquer TV Samsung sem catálogo fixo; os
botões curados deixam de quebrar por ID errado. (+) Reaproveita o socket de controle —
sem nova conexão. (+) Degrada bem: sem resposta, os Favoritos usam o id de reserva e a
lista completa só aparece quando há dados. (+) Cobertura JVM: `TizenProtocolInstalledAppsTest`
(request + parse) e `RemoteSessionInstalledAppsTest` (pede no open e publica o reply).
(−) Os nomes vindos da TV variam (ex.: "Amazon Prime Video"), então o match dos Favoritos
é heurístico (id → nome exato → contém). (−) Ícones reais (via `http://<ip>:8001<icon>`)
ainda não são renderizados — usa-se a inicial; fica como melhoria futura.

**Alternativas.** *Catálogo fixo de IDs* — descartado: é a causa do bug (IDs variam).
*Hard-code por modelo* — inviável de manter. *Só Favoritos com IDs resolvidos (sem lista
completa)* — preterido: o usuário escolheu também expor todos os apps da TV.
