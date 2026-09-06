/* Voorlees Ninja -- alle interactie in de browser. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const opslag = {
    lees(sleutel, standaard) {
      try {
        const waarde = localStorage.getItem(sleutel);
        return waarde === null ? standaard : JSON.parse(waarde);
      } catch (_) { return standaard; }
    },
    schrijf(sleutel, waarde) {
      try { localStorage.setItem(sleutel, JSON.stringify(waarde)); } catch (_) {}
    },
  };

  const staat = {
    profiel: null,
    verhaal: null,
    bladzijde: 0,
    speelt: false,
    programma: [],
    programmaIndex: 0,
    suggesties: [],
    taakId: null,
    peiling: null,
    lengte: opslag.lees('vn_lengte', 4),
    autoblader: opslag.lees('vn_autoblader', true),
    grooteLetters: opslag.lees('vn_grote_letters', false),
    dimmer: opslag.lees('vn_dimmer', 0),
    wakeLock: null,
  };

  // Vangnet: gebruikt zolang Gemini nog geen ideeën heeft geleverd,
  // en als de app offline staat.
  const VASTE_SUGGESTIES = [
    ['🚋', 'Tram over de brug', 'rijdt mee in tram 3 over de Erasmusbrug en zwaait naar alle boten'],
    ['🐘', 'Olifant in Blijdorp', 'helpt in Diergaarde Blijdorp een olifantje dat zijn mama kwijt is'],
    ['🏗️', 'De grote havenkraan', 'bouwt met een enorme havenkraan een brug van blokken'],
    ['⛴️', 'Watertaxi naar zee', 'vaart met de watertaxi naar een eiland vol vriendelijke zeehonden'],
    ['🚒', 'Brandweer voor één nacht', 'wordt één nachtje brandweerman en redt een poesje uit een boom'],
    ['🌈', 'Regenboog in een emmer', 'vangt regendruppels op in een emmer en maakt er een regenboog van'],
    ['🐦', 'Feest van de meeuwen', 'ontdekt dat de meeuwen op het dak een geheim feestje geven'],
    ['🚀', 'Raket naar de maan', 'vliegt in een kartonnen raket langs de maan en weer terug in bed'],
    ['🦖', 'Dino in de zandbak', 'vindt een klein, verlegen dinosaurusje in de zandbak'],
    ['🍟', 'Redding van de patatkraam', 'helpt de patatkraam als alle friet is opgegeten door meeuwen'],
    ['🎠', 'Draaimolen op hol', 'gaat naar de kermis en de draaimolen wil niet meer stoppen'],
    ['🐳', 'Walvis in de haven', 'ziet een walvis in de haven die de weg naar zee kwijt is'],
    ['🧦', 'De verdwenen sok', "zoekt de sok die elke nacht uit de wasmand verdwijnt"],
    ['🚜', 'Schaapjes tellen', 'mag op de tractor bij de boer en helpt de schaapjes tellen'],
    ['⛄', 'Wandelende sneeuwpop', "maakt een sneeuwpop die 's nachts stiekem gaat wandelen"],
    ['🎈', 'Zwevende ballon', 'houdt een ballon vast die hem zachtjes boven de stad optilt'],
    ['🐝', 'Bijtje de weg wijzen', 'helpt een bijtje de weg terug te vinden naar de bloemenkorf'],
    ['🌉', 'Zingende brugverlichting', "ontdekt dat de lichtjes op de brug 's avonds liedjes zingen"],
    ['🚑', 'Beertje weer beter', 'gaat mee met de ziekenwagen en maakt een beertje weer beter'],
    ['🦆', 'Verdwaald eendje', 'brengt een verdwaald eendje terug naar de Maas'],
  ];

  const TIPS = [
    'De verteller kiest zorgvuldig zijn woorden…',
    'De tekenaar slijpt zijn potloden…',
    'Er wordt een spannend, maar veilig avontuur bedacht…',
    'De sterren worden een voor een aangestoken…',
    'Dit duurt ongeveer een minuutje. Even geduld…',
    'Alle plaatjes krijgen dezelfde hoofdpersoon…',
    'De laatste bladzijde wordt lekker slaperig gemaakt…',
  ];

  /* ---------------- Kleine hulpjes ---------------- */
  let meldingTimer = null;
  function meld(tekst, soort = '') {
    const doos = $('melding');
    doos.textContent = tekst;
    doos.className = `melding zichtbaar ${soort}`;
    clearTimeout(meldingTimer);
    meldingTimer = setTimeout(() => { doos.className = 'melding'; }, 4200);
  }

  function toon(id) { $(id).classList.remove('verborgen'); }
  function verberg(id) { $(id).classList.add('verborgen'); }

  async function api(pad, opties = {}) {
    const antwoord = await fetch(pad, {
      credentials: 'same-origin',
      headers: opties.body && !(opties.body instanceof FormData)
        ? { 'Content-Type': 'application/json' } : undefined,
      ...opties,
    });
    if (antwoord.status === 401) {
      naarSlot();
      throw new Error('Pincode vereist');
    }
    const kopie = antwoord.clone();
    let gegevens = null;
    try { gegevens = await antwoord.json(); } catch (_) {}
    if (!antwoord.ok) {
      if (gegevens && gegevens.detail) throw new Error(gegevens.detail);
      // Geen (bruikbare) JSON terug -- vaak een tussenliggende foutpagina
      // (Cloudflare, de proxy) in plaats van een antwoord van de app zelf.
      // Log de ruwe inhoud, zodat dit soort fouten niet stil blijft.
      let ruw = '';
      try { ruw = (await kopie.text()).slice(0, 300); } catch (_) {}
      console.warn(`API-fout ${antwoord.status} op ${pad}:`, ruw || '(leeg antwoord)');
      throw new Error(
          `Er ging iets mis (foutcode ${antwoord.status}). Probeer het nog eens.`
      );
    }
    return gegevens;
  }

  function datumNL(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' });
  }

  /* ---------------- Sterrenhemel ---------------- */
  function maakSterren() {
    const hemel = $('sterren');
    const aantal = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 24 : 70;
    const stukjes = [];
    for (let i = 0; i < aantal; i++) {
      const grootte = Math.random() * 2 + 1;
      stukjes.push(
        `<i class="ster" style="left:${(Math.random() * 100).toFixed(2)}%;` +
        `top:${(Math.random() * 100).toFixed(2)}%;width:${grootte.toFixed(1)}px;` +
        `height:${grootte.toFixed(1)}px;animation-delay:${(Math.random() * 5).toFixed(2)}s"></i>`
      );
    }
    hemel.innerHTML = stukjes.join('');
  }

  /* ---------------- Suggesties ---------------- */
  function naamVanKind() {
    return (staat.profiel && staat.profiel.naam) || 'Leo';
  }

  function suggestieZin(sjabloon) { return `${naamVanKind()} ${sjabloon}`; }

  function vangnetSuggesties() {
    return VASTE_SUGGESTIES.map(([emoji, label, zin]) => ({
      emoji, label, idee: suggestieZin(zin),
    }));
  }

  /* Haalt door Gemini verzonnen ideeën op. Die worden een dag lang op de
     server bewaard, dus dit kost hooguit één aanroep per dag. */
  async function laadSuggesties({ vernieuw = false } = {}) {
    const knop = $('knop-nieuwe-ideeen');
    if (vernieuw) knop.disabled = true;
    try {
      const pad = vernieuw ? '/api/suggesties?vernieuw=true' : '/api/suggesties';
      const antwoord = await api(pad);
      if (antwoord.suggesties && antwoord.suggesties.length) {
        staat.suggesties = antwoord.suggesties;
      }
      if (vernieuw && antwoord.wacht) meld('Even wachten, en dan mag het weer.');
    } catch (fout) {
      console.warn('Suggesties ophalen mislukt', fout);
    } finally {
      knop.disabled = false;
      toonSuggesties();
    }
  }

  function toonSuggesties() {
    const bron = staat.suggesties.length ? staat.suggesties : vangnetSuggesties();
    const gemengd = [...bron].sort(() => Math.random() - 0.5).slice(0, 6);
    $('suggesties').innerHTML = gemengd.map(({ emoji, label, idee }) => {
      const volledig = String(idee).replace(/"/g, '&quot;');
      return `<button class="tegel" type="button" data-idee="${volledig}">` +
             `<span class="emoji">${emoji || '✨'}</span>` +
             `<span>${ontsnap(label)}</span></button>`;
    }).join('');
    $('suggesties').querySelectorAll('.tegel').forEach((tegel) => {
      tegel.addEventListener('click', () => {
        $('idee-veld').value = tegel.dataset.idee;
        $('idee-veld').focus();
      });
    });
  }

  /* ---------------- Toegang ---------------- */
  function naarSlot() {
    verberg('scherm-start');
    verberg('scherm-lezer');
    verberg('scherm-wachten');
    toon('scherm-slot');
    $('pin-invoer').focus();
  }

  async function start() {
    maakSterren();
    zetDimmer(staat.dimmer);
    const gegevens = await fetch('/api/status', { credentials: 'same-origin' })
      .then((r) => r.json()).catch(() => ({ ingelogd: false, pin_vereist: true }));

    if (!gegevens.ingelogd) { naarSlot(); return; }
    staat.profiel = gegevens.profiel;
    if (gegevens.pin_vereist) $('knop-uitloggen').classList.remove('verborgen');
    verberg('scherm-slot');
    toon('scherm-start');
    $('welkomstregel').textContent =
      `Welk avontuur beleeft ${naamVanKind()} vanavond?`;
    $('idee-veld').placeholder =
      `Bijvoorbeeld: ${suggestieZin('brengt een verdwaald eendje terug naar de Maas')}…`;
    toonSuggesties();
    zetLengte(staat.lengte);
    laadPlank();
    laadSuggesties();
  }

  $('pin-formulier').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formulier = new FormData();
    formulier.append('pincode', $('pin-invoer').value);
    try {
      await api('/api/login', { method: 'POST', body: formulier });
      $('pin-invoer').value = '';
      await start();
    } catch (fout) {
      meld(fout.message, 'fout');
      $('pin-invoer').value = '';
    }
  });

  $('knop-uitloggen').addEventListener('click', async () => {
    await api('/api/logout', { method: 'POST' }).catch(() => {});
    location.reload();
  });

  /* ---------------- Boekenplank ---------------- */
  async function laadPlank() {
    try {
      const { verhalen } = await api('/api/verhalen');
      const plank = $('plank');
      $('plank-telling').textContent =
        verhalen.length ? `${verhalen.length} ${verhalen.length === 1 ? 'boekje' : 'boekjes'}` : '';
      if (!verhalen.length) {
        plank.innerHTML = '';
        toon('plank-leeg');
        return;
      }
      verberg('plank-leeg');
      plank.innerHTML = verhalen.map((v) => `
        <button class="boek" type="button" data-id="${v.id}">
          ${v.favoriet ? '<span class="hartje">⭐</span>' : ''}
          <img src="/media/${v.id}/${v.omslag}" alt="" loading="lazy">
          <div class="titel">${ontsnap(v.titel)}</div>
          <div class="datum">${datumNL(v.gemaakt_op)} · ${v.aantal_scenes} bladzijden</div>
        </button>`).join('');
      plank.querySelectorAll('.boek').forEach((boek) => {
        boek.addEventListener('click', () => openVerhaal(boek.dataset.id));
      });
    } catch (fout) {
      console.warn('Boekenplank laden mislukt', fout);
    }
  }

  function ontsnap(tekst) {
    const d = document.createElement('div');
    d.textContent = tekst || '';
    return d.innerHTML;
  }

  /* ---------------- Verhaal maken ---------------- */
  function zetLengte(aantal) {
    staat.lengte = aantal;
    opslag.schrijf('vn_lengte', aantal);
    $('lengte-keuze').querySelectorAll('button').forEach((knop) => {
      knop.setAttribute('aria-pressed', String(Number(knop.dataset.scenes) === aantal));
    });
  }

  $('lengte-keuze').addEventListener('click', (e) => {
    const knop = e.target.closest('button');
    if (knop) zetLengte(Number(knop.dataset.scenes));
  });

  $('knop-verras').addEventListener('click', () => {
    const bron = staat.suggesties.length ? staat.suggesties : vangnetSuggesties();
    const keuze = bron[Math.floor(Math.random() * bron.length)];
    $('idee-veld').value = keuze.idee;
    toonSuggesties();
  });

  $('knop-nieuwe-ideeen').addEventListener('click', () => laadSuggesties({ vernieuw: true }));

  $('knop-maak').addEventListener('click', maakVerhaal);
  $('idee-veld').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) maakVerhaal();
  });

  async function maakVerhaal() {
    const idee = $('idee-veld').value.trim();
    if (idee.length < 3) { meld('Vertel eerst waar het verhaaltje over gaat.', 'fout'); return; }

    $('knop-maak').disabled = true;
    toonWachtscherm(true);
    zetVoortgang('In de wachtrij…', 2);

    try {
      const { taak_id } = await api('/api/genereer', {
        method: 'POST',
        body: JSON.stringify({ prompt: idee, scenes: staat.lengte }),
      });
      staat.taakId = taak_id;
      volgTaak();
    } catch (fout) {
      toonWachtscherm(false);
      $('knop-maak').disabled = false;
      meld(fout.message, 'fout');
    }
  }

  function volgTaak() {
    clearInterval(staat.peiling);
    staat.peiling = setInterval(async () => {
      if (!staat.taakId) { clearInterval(staat.peiling); return; }
      try {
        const taak = await api(`/api/taken/${staat.taakId}`);
        zetVoortgang(taak.stap || '', taak.voortgang || 0);
        if (taak.status === 'klaar') {
          clearInterval(staat.peiling);
          staat.taakId = null;
          $('knop-maak').disabled = false;
          $('idee-veld').value = '';
          toonWachtscherm(false);
          laadPlank();
          toonVerhaal(taak.verhaal);
        } else if (taak.status === 'mislukt') {
          clearInterval(staat.peiling);
          staat.taakId = null;
          $('knop-maak').disabled = false;
          toonWachtscherm(false);
          meld(taak.fout || 'Het verhaaltje maken is mislukt.', 'fout');
        }
      } catch (fout) {
        clearInterval(staat.peiling);
        staat.taakId = null;
        $('knop-maak').disabled = false;
        toonWachtscherm(false);
        meld(fout.message, 'fout');
      }
    }, 1800);
  }

  let tipTimer = null;
  function toonWachtscherm(aan) {
    if (aan) {
      toon('scherm-wachten');
      let index = 0;
      $('wacht-tip').textContent = TIPS[0];
      clearInterval(tipTimer);
      tipTimer = setInterval(() => {
        index = (index + 1) % TIPS.length;
        $('wacht-tip').textContent = TIPS[index];
      }, 6000);
    } else {
      verberg('scherm-wachten');
      clearInterval(tipTimer);
    }
  }

  function zetVoortgang(stap, pct) {
    $('wacht-stap').textContent = stap;
    $('wacht-balk').style.width = `${Math.max(2, Math.min(100, pct))}%`;
    $('wacht-emoji').textContent = pct < 15 ? '📖' : pct < 72 ? '🎨' : pct < 100 ? '🎙️' : '🌙';
  }

  $('knop-wacht-verberg').addEventListener('click', () => {
    toonWachtscherm(false);
    meld('Ik werk op de achtergrond door. Je hoort het als het boekje klaar is.');
  });

  /* ---------------- De lezer ---------------- */
  async function openVerhaal(id) {
    try {
      const verhaal = await api(`/api/verhalen/${id}`);
      toonVerhaal(verhaal);
    } catch (fout) {
      meld(fout.message, 'fout');
    }
  }

  function toonVerhaal(verhaal) {
    staat.verhaal = verhaal;
    staat.bladzijde = 0;
    $('lezer-titel').textContent = verhaal.titel;
    $('lezer-stippen').innerHTML = verhaal.scenes
      .map((_, i) => `<span class="stip" data-nr="${i}"></span>`).join('');
    $('lezer-tekst').classList.toggle('groot', staat.grooteLetters);
    toon('scherm-lezer');
    verberg('scherm-start');
    naarBladzijde(0);
    voorlaadVolgende(1);
  }

  function naarBladzijde(index) {
    const verhaal = staat.verhaal;
    if (!verhaal) return;
    const nieuw = Math.max(0, Math.min(verhaal.scenes.length - 1, index));
    staat.bladzijde = nieuw;
    const scene = verhaal.scenes[nieuw];
    $('lezer-prent').src = `/media/${verhaal.id}/${scene.afbeelding}`;
    $('lezer-prent').alt = `Tekening bij bladzijde ${nieuw + 1}`;
    $('lezer-tekst').textContent = scene.tekst;
    $('lezer-stippen').querySelectorAll('.stip').forEach((stip, i) => {
      stip.setAttribute('aria-current', String(i === nieuw));
    });
    $('knop-vorige').disabled = nieuw === 0;
    $('knop-volgende').disabled = nieuw === verhaal.scenes.length - 1;
    voorlaadVolgende(nieuw + 1);
  }

  function voorlaadVolgende(index) {
    const verhaal = staat.verhaal;
    if (!verhaal || index >= verhaal.scenes.length) return;
    const beeld = new Image();
    beeld.src = `/media/${verhaal.id}/${verhaal.scenes[index].afbeelding}`;
  }

  $('knop-vorige').addEventListener('click', () => { stopVoorlezen(); naarBladzijde(staat.bladzijde - 1); });
  $('knop-volgende').addEventListener('click', () => { stopVoorlezen(); naarBladzijde(staat.bladzijde + 1); });
  $('knop-sluit-lezer').addEventListener('click', sluitLezer);

  function sluitLezer() {
    stopVoorlezen();
    verberg('scherm-lezer');
    toon('scherm-start');
    staat.verhaal = null;
  }

  /* Vegen en toetsenbord */
  let startX = 0, startY = 0;
  $('pagina').addEventListener('touchstart', (e) => {
    startX = e.changedTouches[0].clientX;
    startY = e.changedTouches[0].clientY;
  }, { passive: true });
  $('pagina').addEventListener('touchend', (e) => {
    const dx = e.changedTouches[0].clientX - startX;
    const dy = e.changedTouches[0].clientY - startY;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.6) {
      stopVoorlezen();
      naarBladzijde(staat.bladzijde + (dx < 0 ? 1 : -1));
    }
  }, { passive: true });

  document.addEventListener('keydown', (e) => {
    if ($('scherm-lezer').classList.contains('verborgen')) return;
    if (e.key === 'ArrowRight') { stopVoorlezen(); naarBladzijde(staat.bladzijde + 1); }
    if (e.key === 'ArrowLeft') { stopVoorlezen(); naarBladzijde(staat.bladzijde - 1); }
    if (e.key === 'Escape') sluitLezer();
    if (e.key === ' ') { e.preventDefault(); wisselVoorlezen(); }
    if (e.key === 'r' || e.key === 'R') leesVanafBegin();
  });

  /* ---------------- Voorlezen ---------------- */
  const speler = $('speler');

  $('knop-speel').addEventListener('click', wisselVoorlezen);
  $('knop-herhaal').addEventListener('click', leesVanafBegin);

  /* "Nog een keer!": het hele verhaal opnieuw, vanaf de eerste bladzijde. */
  function leesVanafBegin() {
    if (!staat.verhaal) return;
    const knop = $('knop-herhaal');
    knop.classList.remove('draait');
    void knop.offsetWidth;  // herstart de animatie
    knop.classList.add('draait');
    stopVoorlezen();
    naarBladzijde(0);
    startVoorlezen();
  }

  function wisselVoorlezen() {
    if (staat.speelt) stopVoorlezen(); else startVoorlezen();
  }

  function startVoorlezen() {
    const verhaal = staat.verhaal;
    if (!verhaal) return;
    const map = `/media/${verhaal.id}`;
    staat.programma = [];

    if (staat.bladzijde === 0 && verhaal.titel_audio) {
      staat.programma.push({ url: `${map}/${verhaal.titel_audio}`, bladzijde: 0 });
    }
    for (let i = staat.bladzijde; i < verhaal.scenes.length; i++) {
      const scene = verhaal.scenes[i];
      if (scene.audio) staat.programma.push({ url: `${map}/${scene.audio}`, bladzijde: i });
      if (!staat.autoblader) break;
    }
    if (staat.autoblader && verhaal.slot_audio) {
      staat.programma.push({ url: `${map}/${verhaal.slot_audio}`, bladzijde: null });
    }
    if (!staat.programma.length) { meld('Bij dit verhaaltje zit geen geluid.', 'fout'); return; }

    staat.programmaIndex = 0;
    staat.speelt = true;
    $('knop-speel').textContent = '⏸';
    $('knop-speel').classList.add('speelt');
    $('knop-speel').setAttribute('aria-label', 'Voorlezen pauzeren');
    houdSchermWakker();
    speelHuidigItem();
  }

  function speelHuidigItem() {
    const item = staat.programma[staat.programmaIndex];
    if (!item) { stopVoorlezen(); return; }
    if (item.bladzijde !== null && item.bladzijde !== staat.bladzijde) {
      naarBladzijde(item.bladzijde);
    }
    speler.src = item.url;
    speler.play().catch((fout) => {
      console.warn('Afspelen geweigerd', fout);
      meld('Tik nog een keer op ▶ om het geluid te starten.', 'fout');
      stopVoorlezen();
    });
  }

  speler.addEventListener('ended', () => {
    if (!staat.speelt) return;
    staat.programmaIndex += 1;
    if (staat.programmaIndex >= staat.programma.length) { stopVoorlezen(); return; }
    setTimeout(speelHuidigItem, 600);
  });

  speler.addEventListener('error', () => {
    if (staat.speelt) { meld('Het geluid kon niet geladen worden.', 'fout'); stopVoorlezen(); }
  });

  function stopVoorlezen() {
    staat.speelt = false;
    staat.programma = [];
    try { speler.pause(); } catch (_) {}
    $('knop-speel').textContent = '▶';
    $('knop-speel').classList.remove('speelt');
    $('knop-speel').setAttribute('aria-label', 'Voorlezen starten');
    laatSchermSlapen();
  }

  async function houdSchermWakker() {
    try {
      if ('wakeLock' in navigator && !staat.wakeLock) {
        staat.wakeLock = await navigator.wakeLock.request('screen');
        staat.wakeLock.addEventListener('release', () => { staat.wakeLock = null; });
      }
    } catch (_) { /* niet erg */ }
  }

  function laatSchermSlapen() {
    if (staat.wakeLock) { staat.wakeLock.release().catch(() => {}); staat.wakeLock = null; }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && staat.speelt) houdSchermWakker();
  });

  /* ---------------- Opties voor dit verhaal ---------------- */
  $('knop-lezer-menu').addEventListener('click', () => {
    if (!staat.verhaal) return;
    $('verhaal-opties-titel').textContent = staat.verhaal.titel;
    $('knop-favoriet').textContent = staat.verhaal.favoriet
      ? '⭐ Uit favorieten halen' : '⭐ Favoriet maken';
    $('knop-tekstgrootte').textContent = staat.grooteLetters
      ? '🔠 Gewone letters' : '🔠 Grotere letters';
    $('knop-liedje').textContent = staat.verhaal.liedje
      ? '🎵 Bekijk het liedje' : '🎵 Maak er een liedje van';
    toon('paneel-verhaal');
  });
  $('knop-sluit-verhaal').addEventListener('click', () => verberg('paneel-verhaal'));

  $('knop-liedje').addEventListener('click', () => {
    verberg('paneel-verhaal');
    openLiedje();
  });

  /* ---------------- Slaapliedje ---------------- */
  async function openLiedje({ vernieuw = false } = {}) {
    const verhaal = staat.verhaal;
    if (!verhaal) return;
    toon('paneel-liedje');
    $('liedje-titel').textContent = '🎵 Slaapliedje';

    if (verhaal.liedje && !vernieuw) { vulLiedje(verhaal.liedje); return; }

    toon('liedje-bezig');
    verberg('liedje-inhoud');
    try {
      const start = await api(`/api/verhalen/${verhaal.id}/liedje`, {
        method: 'POST', body: JSON.stringify({ vernieuw }),
      });
      if (start.status === 'klaar') {
        verhaal.liedje = start.liedje;
        vulLiedje(start.liedje);
        return;
      }
      await volgLiedjeTaak(start.taak_id, verhaal);
    } catch (fout) {
      verberg('paneel-liedje');
      meld(fout.message, 'fout');
    }
  }

  /* Net als bij het verhaal zelf: het liedje wordt op de achtergrond
     geschreven, dus we pollen tot de taak klaar of mislukt is. Zo blijft de
     HTTP-verbinding nooit lang genoeg open om op een proxy-timeout (502) te
     stuiten. */
  function volgLiedjeTaak(taakId, verhaal) {
    return new Promise((resolve) => {
      const interval = setInterval(async () => {
        try {
          const taak = await api(`/api/liedje-taken/${taakId}`);
          if (taak.status === 'klaar') {
            clearInterval(interval);
            verhaal.liedje = taak.liedje;
            vulLiedje(taak.liedje);
            resolve();
          } else if (taak.status === 'mislukt') {
            clearInterval(interval);
            verberg('paneel-liedje');
            meld(taak.fout || 'Het liedje maken is mislukt.', 'fout');
            resolve();
          }
        } catch (fout) {
          clearInterval(interval);
          verberg('paneel-liedje');
          meld(fout.message, 'fout');
          resolve();
        }
      }, 1500);
    });
  }

  function vulLiedje(liedje) {
    $('liedje-titel').textContent = `🎵 ${liedje.titel || 'Slaapliedje'}`;
    $('liedje-stijl').value = liedje.stijl || '';
    $('liedje-tekst').value = liedje.tekst || '';
    verberg('liedje-bezig');
    toon('liedje-inhoud');
  }

  async function kopieer(tekst, knop, gelukt) {
    try {
      await navigator.clipboard.writeText(tekst);
    } catch (_) {
      // Oudere browsers, of geen https: dan maar via het invoerveld.
      knop.blur();
      const veld = knop === $('knop-kopieer-stijl') ? $('liedje-stijl') : $('liedje-tekst');
      veld.focus();
      veld.select();
      try { document.execCommand('copy'); } catch (__) {
        meld('Kopiëren lukt niet; selecteer de tekst zelf even.', 'fout');
        return;
      }
    }
    meld(gelukt, 'goed');
  }

  $('knop-kopieer-liedje').addEventListener('click', (e) =>
    kopieer($('liedje-tekst').value, e.currentTarget, 'Songtekst gekopieerd 📋'));
  $('knop-kopieer-stijl').addEventListener('click', (e) =>
    kopieer($('liedje-stijl').value, e.currentTarget, 'Muziekstijl gekopieerd 📋'));
  $('knop-nieuw-liedje').addEventListener('click', () => openLiedje({ vernieuw: true }));
  $('knop-sluit-liedje').addEventListener('click', () => verberg('paneel-liedje'));

  $('knop-favoriet').addEventListener('click', async () => {
    if (!staat.verhaal) return;
    const nieuw = !staat.verhaal.favoriet;
    try {
      await api(`/api/verhalen/${staat.verhaal.id}/favoriet`, {
        method: 'POST', body: JSON.stringify({ favoriet: nieuw }),
      });
      staat.verhaal.favoriet = nieuw;
      verberg('paneel-verhaal');
      meld(nieuw ? 'Bij de favorieten gezet ⭐' : 'Uit de favorieten gehaald', 'goed');
      laadPlank();
    } catch (fout) { meld(fout.message, 'fout'); }
  });

  $('knop-tekstgrootte').addEventListener('click', () => {
    staat.grooteLetters = !staat.grooteLetters;
    opslag.schrijf('vn_grote_letters', staat.grooteLetters);
    $('lezer-tekst').classList.toggle('groot', staat.grooteLetters);
    verberg('paneel-verhaal');
  });

  $('knop-verwijder').addEventListener('click', async () => {
    if (!staat.verhaal) return;
    if (!confirm(`"${staat.verhaal.titel}" echt weggooien?`)) return;
    try {
      await api(`/api/verhalen/${staat.verhaal.id}`, { method: 'DELETE' });
      verberg('paneel-verhaal');
      sluitLezer();
      laadPlank();
      meld('Verhaaltje verwijderd.');
    } catch (fout) { meld(fout.message, 'fout'); }
  });

  $('knop-offline').addEventListener('click', async () => {
    const verhaal = staat.verhaal;
    if (!verhaal) return;
    if (!('caches' in window)) { meld('Deze browser kan geen verhalen offline bewaren.', 'fout'); return; }
    try {
      const map = `/media/${verhaal.id}`;
      const adressen = [`${map}/${verhaal.titel_audio || ''}`, `${map}/${verhaal.slot_audio || ''}`]
        .filter((a) => !a.endsWith('/'));
      verhaal.scenes.forEach((s) => {
        if (s.afbeelding) adressen.push(`${map}/${s.afbeelding}`);
        if (s.audio) adressen.push(`${map}/${s.audio}`);
      });
      const bak = await caches.open('voorlees-verhalen-v1');
      await bak.addAll(adressen);
      verberg('paneel-verhaal');
      meld('Dit boekje werkt nu ook zonder internet 📥', 'goed');
    } catch (fout) {
      meld('Offline bewaren is niet gelukt.', 'fout');
      console.warn(fout);
    }
  });

  /* ---------------- Instellingen ---------------- */
  $('knop-instellingen').addEventListener('click', async () => {
    const p = staat.profiel || {};
    $('in-naam').value = p.naam || '';
    $('in-leeftijd').value = p.leeftijd || 3;
    $('in-plaats').value = p.plaats || '';
    $('in-favorieten').value = p.favorieten || '';
    $('in-uiterlijk').value = p.uiterlijk || '';
    $('in-tempo').value = p.tempo || 0.9;
    $('tempo-waarde').textContent = `${Number(p.tempo || 0.9).toFixed(2)}×`;
    $('in-dimmer').value = staat.dimmer;
    $('dimmer-waarde').textContent = `${staat.dimmer}%`;
    $('in-autoblader').querySelectorAll('button').forEach((knop) => {
      knop.setAttribute('aria-pressed', String((knop.dataset.auto === 'ja') === staat.autoblader));
    });
    toon('paneel-instellingen');
    laadStemmen(p.stem);
  });

  async function laadStemmen(gekozen) {
    const keuze = $('in-stem');
    if (keuze.dataset.geladen === 'ja') { keuze.value = gekozen || keuze.value; return; }
    keuze.innerHTML = '<option>Stemmen ophalen…</option>';
    try {
      const { stemmen } = await api('/api/stemmen');
      if (!stemmen.length) throw new Error('leeg');
      keuze.innerHTML = stemmen.map((s) =>
        `<option value="${s.naam}">${s.naam.replace('nl-NL-', '')} — ${s.geslacht}</option>`).join('');
      keuze.dataset.geladen = 'ja';
      if (gekozen) keuze.value = gekozen;
    } catch (_) {
      keuze.innerHTML = `<option value="${gekozen || 'nl-NL-Wavenet-E'}">${gekozen || 'nl-NL-Wavenet-E'}</option>`;
    }
  }

  $('in-tempo').addEventListener('input', (e) => {
    $('tempo-waarde').textContent = `${Number(e.target.value).toFixed(2)}×`;
  });

  $('in-dimmer').addEventListener('input', (e) => zetDimmer(Number(e.target.value)));

  function zetDimmer(percentage) {
    staat.dimmer = percentage;
    opslag.schrijf('vn_dimmer', percentage);
    $('dimmer').style.opacity = String(percentage / 100);
    const waarde = $('dimmer-waarde');
    if (waarde) waarde.textContent = `${percentage}%`;
  }

  $('in-autoblader').addEventListener('click', (e) => {
    const knop = e.target.closest('button');
    if (!knop) return;
    staat.autoblader = knop.dataset.auto === 'ja';
    opslag.schrijf('vn_autoblader', staat.autoblader);
    $('in-autoblader').querySelectorAll('button').forEach((k) => {
      k.setAttribute('aria-pressed', String(k === knop));
    });
  });

  $('knop-bewaar-instellingen').addEventListener('click', async () => {
    const nieuw = {
      naam: $('in-naam').value.trim() || 'Leo',
      leeftijd: Number($('in-leeftijd').value) || 3,
      plaats: $('in-plaats').value.trim(),
      favorieten: $('in-favorieten').value.trim(),
      uiterlijk: $('in-uiterlijk').value.trim(),
      stem: $('in-stem').value,
      tempo: Number($('in-tempo').value),
    };
    try {
      staat.profiel = await api('/api/profiel', {
        method: 'POST', body: JSON.stringify(nieuw),
      });
      verberg('paneel-instellingen');
      $('welkomstregel').textContent = `Welk avontuur beleeft ${naamVanKind()} vanavond?`;
      meld('Instellingen bewaard ✨', 'goed');
      laadSuggesties();
    } catch (fout) { meld(fout.message, 'fout'); }
  });

  $('knop-sluit-instellingen').addEventListener('click', () => verberg('paneel-instellingen'));

  document.querySelectorAll('.paneel-achtergrond').forEach((laag) => {
    laag.addEventListener('click', (e) => {
      if (e.target === laag) laag.classList.add('verborgen');
    });
  });

  /* ---------------- Service worker ---------------- */
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch((fout) => {
        console.warn('Service worker niet geregistreerd', fout);
      });
    });
  }

  start();
})();
