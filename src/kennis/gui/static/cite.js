// The hit card's Copy citation (#627): the citation's text, fetched from
// the server that wrote it, put on the clipboard, and the entry's label
// changed to the word the page carries. Without a script the entry is a
// link to the citation's page. No sentence here: the words are the
// server's.
document.addEventListener("click", async (event) => {
  const entry = event.target.closest("a.copy-citation");
  if (!entry || !navigator.clipboard) return;
  event.preventDefault();
  const answer = await fetch(entry.dataset.text, { credentials: "same-origin" });
  if (!answer.ok) {
    window.location.assign(entry.href);
    return;
  }
  await navigator.clipboard.writeText(await answer.text());
  const label = entry.querySelector("span");
  if (label) label.textContent = entry.dataset.copied;
});
