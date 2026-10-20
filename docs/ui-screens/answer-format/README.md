# Format jawaban: sebelum dan sesudah

`python scripts/ui_screens.py --answer-format --out docs/ui-screens/answer-format/<before|after>`,
1366 x 768, controller tiruan. Tiga jawaban panjang dari cache run E-04 (dev):

| adegan | sumber | hasil sesudah |
| --- | --- | --- |
| a1-langkah-bernomor-20b | gpt-oss-20b, d005 | pembuka + daftar bernomor 6 butir |
| a2-tahapan-gemini | gemini, d005 | 7 kalimat jadi 4 paragraf (maks. 2 kalimat) |
| a3-biaya-20b | gpt-oss-20b, d040 | 5 kalimat jadi 3 paragraf |

`before/` = app.js sebelum perubahan, `after/` = dengan `answer_format.js`. Aturan: docs/UI-WEB.md,
"Format jawaban di gelembung percakapan".
