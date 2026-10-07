import { Info, Phone } from "lucide-react";

export const DISCLAIMER =
  "This tool provides statistical pattern analysis and experimental time-series modeling for analytical and entertainment purposes only. Lottery drawings are strictly independent random events; no machine learning model can guarantee future winning numbers.";

const NCPG_URL = "https://www.ncpgambling.org/help-treatment/";

/** The responsible-gaming notice. Always on screen above the content, on every page. */
export function Disclaimer() {
  return (
    <aside aria-label="Responsible gaming notice" className="border-b bg-secondary/60">
      <div className="mx-auto flex w-full max-w-6xl items-start gap-2.5 px-4 py-2.5 text-xs leading-relaxed text-muted-foreground sm:px-6 sm:text-[0.8rem]">
        <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-foreground" />
        <p>
          <span className="text-foreground">{DISCLAIMER}</span> Gambling problem? Call or text{" "}
          <a className="font-medium text-foreground underline underline-offset-2" href="tel:18004262537">
            1-800-GAMBLER
          </a>{" "}
          or visit the{" "}
          <a className="font-medium text-foreground underline underline-offset-2" href={NCPG_URL} target="_blank" rel="noreferrer">
            National Council on Problem Gambling
          </a>
          .
        </p>
      </div>
    </aside>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-6 border-t bg-card">
      <div className="mx-auto grid w-full max-w-6xl gap-4 px-4 py-6 text-sm text-muted-foreground sm:grid-cols-2 sm:px-6">
        <div className="flex flex-col gap-2">
          <p className="font-medium text-foreground">Play responsibly</p>
          <p>
            If gambling is causing problems for you or someone you know, free and confidential help is available 24/7 from the
            National Council on Problem Gambling.
          </p>
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <a className="inline-flex items-center gap-1.5 font-medium text-foreground underline underline-offset-2" href="tel:18004262537">
              <Phone className="size-3.5" /> 1-800-GAMBLER
            </a>
            <a className="font-medium text-foreground underline underline-offset-2" href={NCPG_URL} target="_blank" rel="noreferrer">
              ncpgambling.org/help-treatment
            </a>
            <a className="font-medium text-foreground underline underline-offset-2" href="https://www.ncpgambling.org/chat/" target="_blank" rel="noreferrer">
              Live chat
            </a>
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <p className="font-medium text-foreground">About the numbers</p>
          <p>
            Results come from New York State open data, megamillions.com and walottery.com. Every backtest on this site is shown
            next to what pure chance would score, because that is the honest benchmark: past draws do not change the odds of
            future ones.
          </p>
          <p>Not affiliated with any lottery. Age limits apply to lottery play (18 or older in most states).</p>
        </div>
      </div>
    </footer>
  );
}
