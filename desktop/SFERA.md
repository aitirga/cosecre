# Esfer@ a Cosecre — accés integrat i credencials personals

## Accés i configuració

La barra lateral conté **Eines → Esfer@ → Navegador** i **Tauler econòmic**. La branca és plegable i
permet afegir altres opcions de gestió econòmica. Les persones amb rol
Secretari/a (admin) o Administratiu/va poden obrir el navegador; Professor/a no.

**Eines → Esfer@ → Configuració** és un enllaç profund a
**Configuració → General → Esfer@** (`/settings?tab=sfera`). Només l'administrador
pot accedir a aquesta pantalla i modificar la configuració, com a les altres
configuracions de Cosecre. «Desar» confirma el resultat i conserva els canvis al
formulari si el Hub falla. «Descartar» recupera els valors desats.

- **URL d'accés:** adreça inicial editable. HTTPS; HTTP només per a localhost,
  127.0.0.1 o ::1 en proves. No s'admeten credencials a la URL ni paràmetres de
  contrasenya/token. Deixar-la buida desactiva l'accés al navegador.
- **Centre:** referència opcional visible a la capçalera per identificar el
  context. No selecciona automàticament cap centre al portal.
- **Utilitzar el portal de formació:** omple el formulari amb
  `https://formacio.bfgh.aplicacions.ensenyament.gencat.cat/bfgh/gestioeconomica/#/`.
  Cal desar-lo. No modifica el compte ni inicia sessió.

**El meu accés a Esfer@** conté l'usuari de GICAR, la contrasenya i l'opció
**Iniciar sessió automàticament a GICAR**. Cada secretari o secretària configura
les seves pròpies credencials. També és accessible amb **El meu accés** des del
navegador, per als dos rols autoritzats de l'oficina; la configuració compartida
de URL i centre continua reservada a l'administrador.

Una contrasenya buida conserva l'anterior quan l'usuari no canvia. Canviar
l'usuari requereix escriure la seva contrasenya. Després de desar, el camp es
buida i només indica si hi ha una contrasenya guardada. **Eliminar les meves
credencials** elimina exclusivament l'accés personal d'aquest dispositiu.

## On viuen les dades

La URL i el centre es desen a la base de dades **del Hub**, a `AppSetting`, amb
slug `cosecre-sfera` i claus `access_url` i `centre`, mitjançant
`GET/PUT /api/v1/apps/cosecre-sfera/settings`. Les lectures requereixen sessió;
les escriptures requereixen administrador. Tant el PUT del conjunt com el PUT
d'una clau rebutgen camps aliens o credencials. Aquest conjunt és públic per a
les persones autenticades del Hub: no és un magatzem de secrets.

Les cookies, l'emmagatzematge web i la sessió d'Esfer@ es conserven **només al
dispositiu**, a les particions de Chromium sota el directori de dades de
Cosecre (`app.getPath('userData')/Partitions/`). El nom de partició conté un
SHA-256 del Hub normalitzat, l'identificador de compte i l'eina. La sessió es
recupera quan torna el mateix compte al mateix Hub. No es copia la sessió de
Safari ni s'envien tokens del Hub al portal.

Passar entre Navegador i Tauler econòmic conserva la vista del portal oculta,
el centre seleccionat i el context d'accés. Sortir d'aquestes dues pantalles
tanca la vista i les finestres de login, però conserva les cookies.
Recarregar Cosecre, canviar de Hub, tancar la finestra o eliminar els
tokens de Cosecre destrueix també el context actiu. Un altre compte/Hub té una
partició diferent. **Esborrar sessió** demana confirmació, tanca els popups,
esborra cookies, emmagatzematge, memòria cau i autenticació HTTP, i torna a la
URL inicial. Les sessions d'altres comptes/Hubs es conserven separades.

Les credencials personals **no es desen al Hub**. El procés principal manté
`<userData>/sfera-credentials.json`, amb permisos 0600 i contrasenyes xifrades
amb `safeStorage`: Keychain a macOS, DPAPI a Windows i el magatzem de secrets
disponible a Linux. No s'accepta el backend Linux `basic_text` ni una màquina
sense xifrat disponible. Les claus de context són hashes de Hub, compte i eina,
i el renderer només rep usuari, estat de contrasenya guardada i preferència
d'accés automàtic; mai rep la contrasenya desada. No hi ha sincronització de
credencials entre dispositius.

## Navegador dins la mateixa finestra

A l'escriptori, el portal ocupa una `WebContentsView` dins la finestra de
Cosecre: **no es llança cap altra aplicació**. La barra lateral i els controls
Enrere, Endavant, Recarregar, Inici i Configuració són de Cosecre. La capçalera
mostra la URL actual i l'estat de càrrega/error.

La vista es mesura en coordenades de contingut, respecta el zoom i es retalla a
la finestra. Els canvis de mida i el desplaçament actualitzen els límits; quan
s'obre un menú, un diàleg, una superposició o s'oculta el document, la vista
nativa es retira temporalment perquè no tapi la interfície.

Les redireccions HTTPS d'autenticació poden canviar de domini. Els popups de
login es permeten (màxim quatre simultanis), amb la mateixa partició i sense
privilegis de Cosecre; es tanquen en abandonar el navegador. Les descàrregues
utilitzen el diàleg natiu de desament, sense obrir ni executar fitxers. Les
pendents es cancel·len en destruir el context. No es concedeixen permisos de
càmera, micròfon, ubicació o altres dispositius en aquesta fase.

## Per què un iframe web no completa el login

Comprovat el **12 d'octubre de 2026**: l'adreça de formació redirigeix a GICAR.
La pàgina de login respon amb:

```
X-Frame-Options: SAMEORIGIN
Content-Security-Policy: frame-src 'self'; frame-ancestors 'self'; object-src 'none';
```

Això impedeix mostrar el login en un iframe servit per Cosecre. Una sessió
oberta a Safari no prova que el flux de login es pugui incrustar. Esfer@ és exclusiu de l'escriptori: a la versió web no apareixen la branca,
la secció de configuració ni la ruta del navegador. El registre filtra els
mòduls amb `platforms` abans de construir les rutes i la barra lateral.
No es retiren capçaleres, no es desactiva la seguretat web i no es fa un proxy de
credencials per esquivar aquesta restricció.

## Aïllament i extensió

S'ha escollit `WebContentsView`, disponible a Electron **38.8.6**, seguint la
[documentació oficial](https://www.electronjs.org/docs/latest/api/web-contents-view)
i les [recomanacions de seguretat](https://www.electronjs.org/docs/latest/tutorial/security).
No s'utilitza BrowserView (obsolet) ni el tag webview. El portal i els popups
usen sandbox, contextIsolation, webSecurity i nodeIntegration=false, sense
preload ni `window.cosecreDesktop`. No es carreguen protocols file/javascript
ni s'ignoren errors de certificat.

El contracte petit i tipat és `frontend/src/browser/contract.ts`: obertura,
estat, límits/visibilitat, navegació, tancament, neteja de sessió i gestió de l’accés personal sense retorn de secrets. No exposa
execució de JavaScript, lectura de fitxers ni tokens. Cada crida IPC verifica el
renderer principal de Cosecre i l'identificador de la vista activa; el procés
principal consulta el compte i la URL directament al Hub, abans de crear-la.

- `frontend/src/modules/sfera/`: eina, configuració i vista; punt d'entrada per
  a futurs subapartats de gestió econòmica.
- `frontend/src/browser/`: contracte independent del portal i validació URL.
- `desktop/src/main/browser/`: motor, política de navegació i cicle de vida.
- `CosecreModule.settingsSections` i `nav.to`: extensió del registre per a
  seccions modulars a General i enllaços profunds de la barra lateral.

El login té un adaptador privat a `desktop/src/main/browser/sfera-login.ts`.
Només reconeix l'origen HTTPS `autenticaciogicar5.extranet.gencat.cat`, el realm
`gicar-ad`, el formulari `kc-form-login` i una acció del mateix origen a
`/realms/gicar-ad/login-actions/authenticate`. Omple usuari i contrasenya en un
món aïllat i envia el formulari una sola vegada; un canvi de formulari mostra
un avís i conserva l'accés manual. **Identificar-me** permet reintentar
explícitament. Després d'**Esborrar sessió**, no es reconnecta automàticament
fins que la persona ho demana o reobre el navegador. Els segons factors,
CAPTCHA i els proveïdors alternatius d'identitat requereixen intervenció manual.
No s'exporta execució de scripts al renderer ni a cap interfície d'agents.

El contracte de dades és `frontend/src/sfera/contract.ts`; el motor és
`desktop/src/main/sfera/explorer.ts`. L'IPC permet únicament `budgets`,
`suppliers` i `invoices`, amb un identificador de pressupost opcional. No
accepta URL, mètode HTTP, headers, codi ni payload arbitrari. El procés principal
verifica el compte, la configuració i el context actiu; comprova que el
pressupost és de la llista del centre abans de cercar-ne factures. Les dades
retornades es normalitzen amb camps permesos. Les capçaleres pròpies d'Esfer@
es llegeixen amb un adaptador fix al seu sandbox i s'utilitzen només en memòria
del procés principal; no arriben a la interfície ni es desen al Hub.

## Tauler econòmic

**Eines → Esfer@ → Tauler econòmic** (`/eines/sfera/dades`, abans «Resum i dades»)
llegeix Esfer@ en entrar, sense botons de consulta. Obre el portal ocult, espera
l'accés automàtic a GICAR i, si Esfer@ demana triar centre, mostra la mateixa
llista del diàleg «Escolliu el centre» per triar-lo des de Cosecre. Tria el
pressupost general de l'exercici més recent; l'exercici i General/Menjador es
canvien a la capçalera. **Actualitzar** torna a llegir.

Una lectura són vuit peticions fixes en paral·lel (≈1,5 s al portal de formació):

| Petició | Per a |
|---|---|
| `GET /pressupost/centre` | Pressupostos del centre; el pressupost demanat s'hi ha de trobar |
| `GET /pressupost/estat/{id}` | «Estat d'execució del pressupost»: totals, cobraments, pagaments i totes les partides |
| `GET /compteBancari/findByCentre`, `GET /caixaEfectiu/cerca` | Saldos actuals de bancs i caixes |
| `GET /consulta/ldo?dataInici&dataFi&idPressupost` | Llibre diari de l'exercici. **És de tot el centre**, independentment del pressupost |
| `POST /factura/cerca/filtre`, `POST /ingres/cerca/filtre` | Factures i ingressos del pressupost (cerques; no escriuen) |
| `GET /facturaElectronica/pendents` | Factures electròniques per registrar |

Seccions:

- **Indicadors:** tresoreria actual, ingressos reconeguts i despesa executada
  sobre el pressupostat, disponible per gastar, romanent, cobraments i pagaments.
- **Resum:** saldo diari de tresoreria (només l'exercici més recent: es
  reconstrueix des del saldo actual restant els moviments del llibre diari),
  cobraments i pagaments per mes, comptes i caixes, avisos (partides amb excés,
  saldos negatius, desequilibri, factures/ingressos pendents, factura
  electrònica), partides amb més execució, proveïdors i aportadors principals i
  darrers moviments de tresoreria.
- **Partides:** despeses o ingressos amb subpartides plegables, fons, cerca,
  filtre d'excés i ordenació. Els totals sumen només partides, perquè una
  partida ja inclou les seves subpartides.
- **Fons finalistes:** per codi finalista, ingrés previst i reconegut, despesa
  pressupostada, executada i per gastar.
- **Factures i ingressos:** cerca, filtre per proveïdor/aportador i pendents,
  ordenació i detall.

Criteris: un assentament amb dues potes de tresoreria que sumen zero (traspàs
banc–caixa) no compta com a cobrament ni pagament. Els colors són fixos:
blau = ingressos/cobraments, coral = despeses/pagaments, vermell només per a
excés, sempre amb text. L'IBAN, el token i les capçaleres no travessen el pont;
el resultat viu en memòria de la finestra (no al disc ni al Hub). Esfer@ és la
font oficial; el tauler no en substitueix els informes.

Codi: `desktop/src/main/sfera/dashboard.ts` (lector fix),
`frontend/src/sfera/dashboard.ts` (contracte),
`frontend/src/modules/sfera/DashboardView.vue` i `dashboard/`. El pont de
consultes anterior (`sferaData.query`) es manté per a la prova d'extractes;
`ExplorerView.vue` ja no té ruta.

Limitat, com el pont anterior, al **portal de formació** verificat; respostes de
12 MB com a màxim.

## Prova d'extractes a factures

**Eines → Sfer@ → Prova d'extractes** és una prova sintètica local. Genera
tres moviments ficticis: dues despeses de 121,00 € i 39,95 €, i un ingrés de
250,00 €. **Preparar factures** converteix les despeses en dos esborranys
(160,95 € en total) i exclou l'ingrés. Es poden editar data, concepte, import,
proveïdor i partida del catàleg fictici.

Els esborranys inclouen número de factura, document intern, dates, pressupost,
proveïdor, línia imputada a una partida, imports i venciment pendent amb banc.
Els números comencen per `COSECRE-POC-`; les observacions identifiquen les dades
com a fictícies. La prova fixa IVA deduïble i IRPF a zero; no infereix impostos
ni proveïdor a partir de l'extracte. No marca cap factura com a pagada.

**Executar prova sintètica** usa un simulador amb estat que valida, registra i
rellegeix les factures. Repeteix la mateixa prova sense duplicar registres.
La pantalla mostra els codis retornats, imports, peticions simulades i temps,
i permet inspeccionar el JSON preparat. Les rutes de validar/desar coincideixen
amb les observades al portal; `/services/factura/poc/creades` és una ruta pròpia
del simulador. Les durades no representen la latència del portal real.

El mode sintètic conserva els registres només en aquesta pantalla.
**Connectar amb Esfer@ de formació** carrega els catàlegs reals de la sessió
oberta al navegador. Cal seleccionar pressupost, banc, proveïdor i partida
per a cada despesa. **Preparar factures** crea una revisió amb números únics;
**Crear aquestes factures a Esfer@ de formació** cerca possibles duplicats,
valida, desa i rellegeix cada factura per comprovar-ne pressupost, proveïdor
i import. La pantalla mostra identificadors, codis i temps de les peticions.
El pont només accepta l'identificador d'una revisió pròpia de la sessió;
no accepta URLs, mètodes ni payloads d'escriptura arbitraris.

Aquesta prova queda limitada al portal de formació, pressupostos editables
de 2026, centres que no liquiden IVA i un màxim de dues factures de 200 €
cadascuna. Les factures queden pendents; no executa pagaments. Les escriptures
usen el client HTTP del portal, amb el seu context de navegador, i les
lectures usen la sessió privada de Cosecre. Un desament ambigu es consulta
abans de reintentar. **Generar extracte fictici** reinicia els esborranys.

`just check-sfera-poc` prova imports, dates, proveïdors, duplicats, imports de
línies/venciments, errors de validació i absència de desament després d'error.
`just check-sfera` afegeix el recorregut real de la interfície d'escriptori,
verifica les dues factures i comprova que la prova no crida el portal.

## Resultats de l'exploració del portal

El 12 d'octubre de 2026 s'ha inspeccionat la mateixa aplicació autenticada en
una còpia privada del perfil. El portal usa AngularJS 1.5.7 (versió
12.40.2_B000). S'han invocat les accions de selecció del centre, pressupost i
pestanya de factures directament al portal; no s'ha simulat el punter del
sistema. El centre [centre de prova] ha retornat **14 pressupostos**, **413 proveïdors**
i **306 factures** del pressupost General de 2026.

També s'han executat aquestes tres consultes des del nou pont de dades de
Cosecre, amb el portal ocult i la sessió conservada. Una passada ha mesurat
48 ms per a pressupostos, 147 ms per a proveïdors i 1.673 ms per a factures
(inclou verificar la llista de pressupostos). Són mesures d'una prova, no
una garantia de rendiment. La capçalera `USR_ROL` del client pot ser numèrica:
es conserva convertida a text HTTP, sense ometre-la. La falta d'aquesta
capçalera ha provocat timeouts durant la investigació; la prova de regressió
inclou headers numèrics. L'evidència local és `research/explorer-proof.json`.

| Via | Evidència i ús proposat | Límit |
|---|---|---|
| HTTP amb la sessió de Cosecre | Lectura JSON de pressupostos, proveïdors i cerca de factures. Base del nou resum. | API interna del portal; no és un contracte públic documentat. Requereix cookies, token i centre propis d'Esfer@. |
| DOM i funcions de l'aplicació | Selecció del context i obertura del formulari de nova factura comprovades sense ratolí. Pot preparar formularis respectant les regles de la interfície. | Depèn de selectors, AngularJS i la versió del portal. No s'exposa execució arbitrària als agents. |
| Protocol de depuració del navegador | Ha permès observar les peticions i bloquejar escriptures en la prova. | Eina de diagnòstic local, sense port remot públic; no substitueix permisos ni validacions comptables. |
| Integració oficial | Si el proveïdor publica o facilita una API, seria la via preferible per a un contracte estable. | No s'ha identificat una API externa oficial documentada en aquesta exploració. |

Les lectures verificades utilitzen la base
`/bfgh/AppJava/bfgh_gesteco/services`:

- `GET /pressupost/centre`: pressupostos del centre actiu.
- `GET /proveidor/cerca`: proveïdors del centre actiu.
- `POST /factura/cerca/filtre`: cerca, tot i utilitzar POST; filtres construïts
  pel procés principal amb l'exercici i pressupost verificats.

S'ha llegit el detall d'una factura amb `GET /factura/{id}` (200), incloent
l'esquema de línies (`partidasFactura`) i venciments (`vencimentsFactura`). També
s'han identificat `PUT /factura/validate` i `PUT /factura/desa` en el flux de
desament, però **no s'han executat**. Obrir una factura nova només ha carregat
el formulari i els catàlegs de suport. El formulari conté proveïdor, número de
factura, dates comptable/document, descripció, línies i venciments. El codi
comprova pressupost editable, impostos, imports de línies i venciments abans
de desar; reconstruir un payload mínim sense aquestes regles seria insuficient.

Per a una fase d'escriptura: preparar un esborrany amb centre, pressupost,
proveïdor, partides, impostos i venciments resolts; mostrar-ne la revisió;
validar amb les regles del portal; registrar només l'esborrany autoritzat i
rellegir el resultat. Cal comprovar duplicats i gestionar els casos en què
una resposta de desament es perd abans de reintentar. Pagaments, anul·lacions,
abonaments i factura electrònica tenen circuits diferents.

Una funció d'exportació inspeccionada al client conté un id de pressupost fix
(34120) diferent del seleccionat. No s'ha utilitzat ni s'ha confirmat que sigui
el camí actiu de la interfície. Cal verificar context i descàrrega abans
d'automatitzar aquest exportador.

Referències: [sessió i fetch d'Electron](https://www.electronjs.org/docs/latest/api/session#sesfetchinput-init),
[protocol de depuració](https://www.electronjs.org/docs/latest/api/debugger),
[manual de factures de la Generalitat](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc2/ap24)
i [informes i extraccions](https://ateneu.xtec.cat/wikiform/wikiexport/esfera/mge1/bloc5/ap51).

## Verificació reproduïble

```
just check-sfera
just check
just build
```

`check-sfera` usa l'Electron instal·lat, el frontend construït i una pàgina/Hub
locals controlats. Crea un directori de dades temporal, mai els comptes o la
base de dades habituals. Comprova navegació, permisos, formulari, cookies,
aïllament, popups, dimensions, diàlegs, errors, xifrat i separació de
credencials personals. El formulari GICAR simulat es proporciona mitjançant
un protocol interceptat només a la sessió temporal: les credencials sintètiques
no s'envien a cap servidor extern. Les captures i el resultat
queden a `output/playwright/sfera/`, ignorat per Git. El portal de dades
simulat també s'intercepta localment; comprova el resum, les tres consultes,
els temps, el canvi de pantalles i el rebuig d'operacions o pressupostos aliens.

`just explore-sfera` executa l'exploració de lectura amb una còpia de
`SFERA_PROFILE` (per defecte la còpia privada anterior de la prova interactiva).
El Hub d'aquell perfil ha de continuar accessible. Les passes actuals
seleccionen el centre [centre de prova] i el pressupost General 2026: cal adaptar-les
per a un altre context. S'eliminen només les dades temporals de la còpia creada;
el perfil original no es modifica. Les captures, esquemes i respostes reals
contenen dades privades i es desen a `output/playwright/sfera/research/`,
ignorat per Git, amb permisos 0700/0600. No es desen les capçaleres de secrets.
La prova bloqueja les peticions d'escriptura, amb l'excepció de l'autenticació
i el POST de cerca verificat; no crida validar/desar cap factura.

El 12 d'octubre de 2026 s'ha verificat també el login real: després que la
persona desés el seu accés a la configuració, s'ha esborrat la sessió del portal
i **Identificar-me** ha enviat les credencials desades a GICAR sense reescriure-les.
S'ha confirmat visualment la sessió autenticada, la selecció del centre
[centre de prova] i el llistat de Gestió econòmica (14 resultats), dins la mateixa finestra
amb la barra lateral de Cosecre. No s'ha modificat cap registre comptable.
L'evidència sense credencials és `output/playwright/sfera/real-authentication.json`.

El perfil interactiu utilitzat en aquesta comprovació és de prova, separat del
perfil normal de Cosecre; se n'ha preservat una còpia privada a
`output/playwright/sfera/private-profile/` (ignorada per Git). Les credencials
reals no formen part dels tests sintètics, ni s'han recuperat de Safari.

La [documentació de safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)
explica les garanties diferents de cada sistema. A macOS, les versions sense
signatura consistent poden tornar a demanar accés al Keychain en actualitzar.
Electron 38.8.6 disposa de l'API síncrona; no s'utilitzen mètodes asíncrons que
només apareixen en versions posteriors.
