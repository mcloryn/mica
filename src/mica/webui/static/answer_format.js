// Format tampilan jawaban MICA (tampilan saja): teks jawaban -> blok paragraf/daftar bernomor.
// Setara mica.webui.answer_format (versi acuan Python, diuji pytest + uji kesetaraan lewat Edge).
// Fungsi murni: tidak menyentuh DOM, tidak mengubah kata; app.js membangun elemennya dengan
// createElement/textContent. Teks TTS, prompt, dan JSON ViewModel tidak berubah.
// Aturan berurutan: (a) baris baru asli dipertahankan, (b) enumerasi dalam kalimat jadi daftar
// bernomor, (c) blok > MAX_SENTENCES_PER_PARAGRAPH kalimat dipecah jadi paragraf.
"use strict";

window.MicaAnswerFormat = (() => {
  // Nilai desain tampilan (bukan hasil ukur): paling banyak 2 kalimat per paragraf.
  const MAX_SENTENCES_PER_PARAGRAPH = 2;
  // singkatan bertitik yang bukan akhir kalimat (huruf kecil, dengan titik)
  const ABBREVIATIONS = new Set([
    "rp.", "no.", "nomor.", "dll.", "dsb.", "dst.", "jl.", "jln.", "prof.", "dr.", "drs.",
    "dra.", "ir.", "h.", "hj.", "st.", "tlp.", "telp.", "hlm.", "kab.", "kec.", "kel.",
    "sdr.", "bpk.", "yth.", "a.n.", "u.p.", "s.kom.", "s.e.", "s.ak.", "s.h.", "m.kom.",
    "m.m.", "m.sc.", "m.si.", "m.ak.", "ph.d.", "t.a.",
  ]);
  const DOTTED = /^(?:[A-Za-z]{1,4}\.){2,}$/; // S.Kom., M.Sc., Ph.D., T.A.
  // angka desimal, jam, tanggal, URL, email tidak punya spasi setelah titik: tidak pernah cocok
  const BOUNDARY = /[.!?]+["')\]”’]*\s+(?=[A-Z0-9"'(“‘])/g;
  const LEADING_OPEN = /^["'(\[“‘]+/;
  const ENUM_STYLES = [
    /(?:^|(?<=\s))\((\d{1,2})\)\s+/g, // (1) (2)
    /(?:^|(?<=\s))(\d{1,2})\)\s+/g, // 1) 2)
    /(?:^|(?<=\s))(\d{1,2})\.\s+/g, // 1. 2.
  ];
  const LINE_ITEM = /^\s*(?:\((\d{1,2})\)|(\d{1,2})[.)])\s+(.*\S)\s*$/;
  const ITEM_TRAIL = /[\s;,]+$/;
  const NEWLINE = /\r\n|\r|\n/;

  function splitSentences(text) {
    text = text.trim();
    const out = [];
    let start = 0;
    for (const m of text.matchAll(BOUNDARY)) {
      if (text[m.index] === ".") {
        const words = text.slice(0, m.index + 1).split(/\s+/).filter(Boolean);
        const word = words.length ? words[words.length - 1].replace(LEADING_OPEN, "") : "";
        if (ABBREVIATIONS.has(word.toLowerCase()) || DOTTED.test(word)) continue;
      }
      const end = m.index + m[0].length;
      const sentence = text.slice(start, end).trim();
      if (sentence) out.push(sentence);
      start = end;
    }
    const rest = text.slice(start).trim();
    if (rest) out.push(rest);
    return out;
  }

  function paragraphs(text) { // aturan c
    const s = splitSentences(text);
    const n = MAX_SENTENCES_PER_PARAGRAPH;
    const out = [];
    for (let i = 0; i < s.length; i += n) out.push({ type: "p", text: s.slice(i, i + n).join(" ") });
    return out;
  }

  function enumeration(text) { // nomor 1, 2, 3, ... berurutan, gaya sama, minimal 2 butir
    for (const style of ENUM_STYLES) {
      const chain = [];
      for (const m of text.matchAll(style)) {
        if (Number(m[1]) === chain.length + 1) chain.push(m);
      }
      if (chain.length >= 2) return chain;
    }
    return null;
  }

  const item = (text) => text.trim().replace(ITEM_TRAIL, "");
  const markEnd = (m) => m.index + m[0].length;

  function formatLine(line) { // aturan b
    const chain = enumeration(line);
    if (chain === null) return paragraphs(line);
    const blocks = paragraphs(line.slice(0, chain[0].index));
    const items = [];
    for (let i = 0; i + 1 < chain.length; i++) items.push(item(line.slice(markEnd(chain[i]), chain[i + 1].index)));
    const last = splitSentences(line.slice(markEnd(chain[chain.length - 1])));
    items.push(last.length ? item(last[0]) : "");
    blocks.push({ type: "ol", start: 1, items });
    return blocks.concat(paragraphs(last.slice(1).join(" ")));
  }

  function formatAnswer(text) {
    const blocks = [];
    for (const line of text.split(NEWLINE)) {
      const m = enumeration(line) === null ? LINE_ITEM.exec(line) : null;
      if (m) { // aturan a: baris bernomor berurutan digabung jadi satu daftar
        const number = Number(m[1] || m[2]);
        const prev = blocks.length ? blocks[blocks.length - 1] : null;
        if (prev && prev.type === "ol" && prev.start + prev.items.length === number) prev.items.push(m[3]);
        else blocks.push({ type: "ol", start: number, items: [m[3]] });
      } else if (line.trim()) {
        blocks.push(...formatLine(line));
      }
    }
    return blocks;
  }

  return { MAX_SENTENCES_PER_PARAGRAPH, splitSentences, formatAnswer };
})();
