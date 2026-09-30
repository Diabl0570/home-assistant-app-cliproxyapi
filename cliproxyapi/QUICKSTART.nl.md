# CLIProxyAPI op Home Assistant OS

Deze Home Assistant-app draait de proxy op je eigen amd64-apparaat. De AI-modellen blijven bij je provider draaien.

1. Voeg na publicatie `https://github.com/Diabl0570/home-assistant-app-cliproxyapi#stable` toe bij **Instellingen → Apps → Appstore → ⋮ → Repositories**.
2. Installeer **CLIProxyAPI**.
3. Vul bij Configuratie minstens één `api_keys` in. Dit is de sleutel voor clients, niet je provider-account.
4. Kies een andere, willekeurige `management_password` van minstens 24 tekens. Genereer bijvoorbeeld twee verschillende waarden met `openssl rand -hex 32`.
5. Start de app en zet starten bij opstarten aan.
6. Open **Web UI**, meld je aan met het beheerwachtwoord en voeg je provider toe. Je kunt ook een bestaand CLIProxyAPI OAuth-authbestand importeren.
7. Gebruik bij clients `http://192.168.178.142:8317/v1` als je Home Assistant dat IP-adres nog heeft, met een sleutel uit `api_keys`.

Providerinstellingen en OAuth-inloggegevens blijven behouden bij herstarten en bijwerken. Je app-configuratie bepaalt bij iedere start opnieuw de client- en beheersleutels. Maak een Home Assistant-back-up vóór updates; die bevat gevoelige inloggegevens.

Een OAuth-login kan naar localhost op je computer verwijzen. Plak waar de beheerpagina dat ondersteunt de volledige uiteindelijke callback-URL terug, of importeer een authbestand. Alleen een extra callbackpoort openen lost een localhost-redirect niet op.

Updates verschijnen via de normale **Bijwerken**-knop zodra een geteste nieuwe appversie is gepubliceerd. Zet poort 8317 niet open op internet. Meer uitleg: [Engelse documentatie](DOCS.md).
