"""Bounded, best-effort DOM diagnostics; never changes message delivery."""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger


# Inspect all media-like nodes, independently of the production selectors.
DOM_DETAILS = r"""el => ({
  html: el.outerHTML,
  text: el.innerText,
  media: Array.from(el.querySelectorAll(
    'img, video, source, canvas, a[href], [style*="background"], ' +
    '[class*="media"], [class*="photo"], [class*="video"], [class*="attach"]'
  )).map(n => ({
    tag: n.tagName, class: n.className?.baseVal ?? n.className,
    src: n.getAttribute('src'), currentSrc: n.currentSrc || null,
    srcset: n.getAttribute('srcset'), poster: n.getAttribute('poster'),
    href: n.getAttribute('href'), style: n.getAttribute('style'),
    complete: n.complete, naturalWidth: n.naturalWidth,
    readyState: n.readyState,
    parents: Array.from((function* () {
      let p = n.parentElement;
      while (p && p !== el) { yield p; p = p.parentElement; }
    })()).map(p => p.tagName + '.' + String(p.className).replaceAll(' ', '.'))
  }))
})"""


class MediaDebug:
    def __init__(self):
        self.enabled = os.getenv('MAX_MEDIA_DEBUG', 'true').lower() == 'true'
        self.root = Path(os.getenv('MAX_MEDIA_DEBUG_DIR', '/data/media-debug'))
        self.interval = max(1, int(os.getenv('MAX_MEDIA_DEBUG_INTERVAL', '60')))
        self.keep = max(1, int(os.getenv('MAX_MEDIA_DEBUG_KEEP', '20')))
        self.last_attempt = None
        self.last_digest = None

    async def capture(self, page, bubbles, parsed, *, reason=None):
        if not self.enabled:
            return
        now = time.monotonic()
        if self.last_attempt is not None and now - self.last_attempt < self.interval:
            return
        self.last_attempt = now
        try:
            records = []
            for bubble, info in zip(bubbles, parsed):
                dom = await bubble.evaluate(DOM_DETAILS)
                reasons = []
                if info is None:
                    reasons.append('not_recognized')
                elif info.get('type') == 'text' and dom['media']:
                    reasons.append('text_with_media_candidates')
                records.append({'parsed': info, 'observations': reasons, 'dom': dom})
            # HTML can contain volatile playback/UI attributes. Compare extracted
            # content and media URLs instead, so identical polls do not fill disk.
            signature = [{'parsed': r['parsed'], 'text': r['dom']['text'],
                          'media': r['dom']['media']} for r in records]
            # No bubbles can mean login, loading, or changed markup. Include the
            # page HTML so a changed failure screen is captured on the next poll.
            page_html = await page.content() if not records else None
            signature = {'messages': signature, 'reason': reason,
                         'page_url': page.url, 'empty_page_html': page_html}
            digest = hashlib.sha256(json.dumps(signature, ensure_ascii=False,
                                                sort_keys=True).encode()).hexdigest()
            if digest == self.last_digest:
                return
            chat = hashlib.sha256(page.url.encode()).hexdigest()[:12]
            directory = self.root / chat
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            base = directory / stamp
            # Rotate before writing, including partial captures from past failures.
            stamps = sorted({p.stem for p in directory.iterdir()
                             if p.suffix in {'.json', '.html', '.png'}})
            for old in stamps[:max(0, len(stamps) - self.keep + 1)]:
                for suffix in ('.json', '.html', '.png'):
                    (directory / (old + suffix)).unlink(missing_ok=True)
            base.with_suffix('.json').write_text(json.dumps({
                'captured_at_utc': stamp, 'page_url': page.url,
                'reason': reason, 'messages': records,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            base.with_suffix('.html').write_text(
                page_html if page_html is not None else await page.content(), encoding='utf-8'
            )
            # Screenshot failure must not discard useful DOM diagnostics.
            try:
                await page.screenshot(path=str(base.with_suffix('.png')), timeout=5000)
            except Exception as exc:
                logger.warning('MAX media debug: screenshot failed ({})', type(exc).__name__)
            self.last_digest = digest
            logger.info('MAX media debug: {} ({} messages)', base.with_suffix('.json'), len(records))
        except Exception as exc:
            logger.warning('MAX media debug: capture failed ({})', type(exc).__name__)
