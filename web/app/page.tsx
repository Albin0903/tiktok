"use client";
import {describeTaxChange} from "./tax-change";

import {useState, type FormEvent} from "react";

const api = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const euros = new Intl.NumberFormat("fr-FR", {style: "currency", currency: "EUR", maximumFractionDigits: 0});
const labels = {
  salarie_non_cadre: "Salarié non-cadre", salarie_cadre: "Salarié cadre", retraite: "Retraité",
  independant: "Indépendant", chomeur: "Au chômage", inactif: "Sans activité",
};
type Status = keyof typeof labels;
type Profile = {
  revenu_net_imposable_mensuel: number; age: number; enfants: number;
  carburant_mensuel: number; energie_mensuelle: number; statut: Status;
  couple: boolean; logement: string;
  loyer_mensuel: number | null; zone_apl: 1 | 2 | 3; age_enfant: number;
  revenu_brut_mensuel: number | null; logement_conventionne: boolean;
};
type Result = {
  lignes: {poste: string; gel_eur: number | null; plf_eur: number | null; delta_eur: number | null}[];
  source_ref: string; hypotheses: string[]; annee_revenus: string;
  variation_revenu_disponible_mensuelle_eur: number;
  hypotheses_appliquees: {loyer_mensuel: number; zone_apl: number; age_enfant: number; revenu_brut_mensuel: number | null; brut_saisi: boolean; logement_conventionne: boolean};
  source_loyer: string;
};

const initial: Profile = {
  revenu_net_imposable_mensuel: 2500, age: 35, enfants: 0, carburant_mensuel: 0,
  energie_mensuelle: 0, statut: "salarie_non_cadre", couple: false, logement: "locataire",
  loyer_mensuel: null, zone_apl: 2, age_enfant: 10, revenu_brut_mensuel: null, logement_conventionne: false,
};
const presets = [
  ["Salarié seul", initial],
  ["Couple avec enfants", {...initial, couple: true, enfants: 2, revenu_net_imposable_mensuel: 4500}],
  ["Retraité seul", {...initial, age: 69, revenu_net_imposable_mensuel: 4000, statut: "retraite"}],
] satisfies [string, Profile][];
const lines: Record<string, string> = {
  impot_revenu: "Impôt sur le revenu", csg_crds: "CSG / CRDS",
  cotisations: "Cotisations et contributions", prime_activite: "Prime d’activité",
  aide_logement: "Aide au logement", allocations_familiales: "Allocations familiales",
  prestations_sociales: "Prestations sociales", revenu_disponible: "Revenu disponible",
};
const sliders = [
  ["revenu_net_imposable_mensuel", "Revenu net imposable du foyer", 0, 20000, 50, "€/mois"],
  ["age", "Âge", 18, 100, 1, "ans"],
  ["enfants", "Enfants à charge", 0, 6, 1, ""],
  ["carburant_mensuel", "Carburant", 0, 800, 10, "€/mois"],
  ["energie_mensuelle", "Énergie du logement", 0, 800, 10, "€/mois"],
] as const;
const number = new Intl.NumberFormat("fr-FR");
const amount = (value: number | null) => value === null ? "—" : euros.format(value);

export default function Home() {
  const [profile, setProfile] = useState(initial);
  const [result, setResult] = useState<Result | null>(null);
  const [submitted, setSubmitted] = useState<Profile | null>(null);
  const [pending, setPending] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState("");

  async function simulate(event: FormEvent) {
    event.preventDefault();
    setPending(true); setError(""); setResult(null);
    try {
      const response = await fetch(`${api}/api/simulate`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(profile),
      });
      if (!response.ok) throw Error("Vérifiez les données du profil puis relancez le calcul.");
      setResult(await response.json()); setSubmitted(profile);
    } catch (failure) {
      setError(failure instanceof TypeError ? "Le moteur local est indisponible. Démarrez l’API et réessayez."
        : (failure as Error).message);
    } finally {setPending(false);}
  }

  async function share() {
    if (!submitted) return;
    setSharing(true); setError("");
    try {
      const response = await fetch("/api/carte", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(submitted),
      });
      if (!response.ok) throw Error("Carte indisponible. Relancez la simulation puis réessayez.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = "ma-carte-2027.png"; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {setError((failure as Error).message);}
    finally {setSharing(false);}
  }

  const delta = result?.variation_revenu_disponible_mensuelle_eur ?? 0;
  const applied = result?.hypotheses_appliquees;
  const ir = result?.lignes.find(line => line.poste === "impot_revenu");
  const taxChange = ir?.delta_eur == null ? null : describeTaxChange(ir.delta_eur);
  const changed = submitted !== null && profile !== submitted;
  return <main>
    <header className="masthead"><a href="/">Vérité Fiscale <strong>2027</strong></a><span>PLF déposé · ex ante</span></header>
    <h1>Que change<br/>le PLF 2027&nbsp;?</h1>
    <p className="intro">Comparez l’impôt, les aides et le revenu disponible de votre foyer avec un scénario où le barème reste gelé.</p>
    <div className="workspace">
      <form onSubmit={simulate} className="profile">
        <h2>Votre foyer</h2>
        <fieldset disabled={pending}>
          <legend>Profils rapides</legend>
          <div className="presets">{presets.map(([label, value]) => <button type="button" key={label}
            aria-pressed={profile === value} onClick={() => setProfile(value)}>{label}</button>)}</div>
          <div className="selects">
            <label>Activité<select value={profile.statut} onChange={(event) => setProfile({
              ...profile, statut: event.target.value as Status, revenu_brut_mensuel: null,
              revenu_net_imposable_mensuel: event.target.value === "inactif" ? 0 : profile.revenu_net_imposable_mensuel,
            })}>
              {Object.entries(labels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select></label>
            <label>Foyer<select value={Number(profile.couple)} onChange={(event) => setProfile({...profile, couple: event.target.value === "1"})}>
              <option value={0}>Seul</option><option value={1}>Imposition commune</option>
            </select></label>
            <label>Logement<select value={profile.logement} onChange={(event) => setProfile({...profile, logement: event.target.value})}>
              <option value="locataire">Locataire</option><option value="proprietaire">Propriétaire</option>
              <option value="loge_gratuitement">Logé gratuitement</option>
            </select></label>
          </div>
          {sliders.map(([key, label, min, max, step, unit]) => <label key={key} className="slider">
            <span>{label}<output htmlFor={key}>{number.format(profile[key])} {unit}</output></span>
            <input id={key} type="range" min={min} max={max} step={step} value={profile[key]}
              onChange={(event) => setProfile({...profile, [key]: Number(event.target.value)})}/>
          </label>)}
          <details>
            <summary>Affiner mes hypothèses</summary>
            <div className="selects">
              {profile.logement === "locataire" && <>
                <label>Loyer hors charges, €/mois<input className="number-field" type="number" min={0} step="0.01"
                  placeholder="650" value={profile.loyer_mensuel ?? ""}
                  onChange={(e) => setProfile({...profile, loyer_mensuel: e.target.value === "" ? null : Number(e.target.value)})}/></label>
                <label>Zone d’aide au logement<select value={profile.zone_apl}
                  onChange={(e) => setProfile({...profile, zone_apl: Number(e.target.value) as 1 | 2 | 3})}>
                  <option value={1}>Zone 1</option><option value={2}>Zone 2</option><option value={3}>Zone 3</option>
                </select></label>
                <label className="check"><input type="checkbox" checked={profile.logement_conventionne}
                  onChange={(e) => setProfile({...profile, logement_conventionne: e.target.checked})}/> Logement conventionné</label>
              </>}
              {profile.enfants > 0 && <label>Âge des enfants<input className="number-field" type="number" min={0} max={17}
                value={profile.age_enfant}
                onChange={(e) => setProfile({...profile, age_enfant: Number(e.target.value)})}/></label>}
              {profile.statut !== "independant" && profile.statut !== "inactif" && <label>Brut du foyer, €/mois<input className="number-field" type="number" min={0}
                step="0.01" placeholder="Calculé par défaut" value={profile.revenu_brut_mensuel ?? ""}
                onChange={(e) => setProfile({...profile, revenu_brut_mensuel: e.target.value === "" ? null : Number(e.target.value)})}/></label>}
            </div>
            <p className="note">Le brut saisi remplace le net imposable pour le calcul. Le loyer par défaut est une estimation hors charges.</p>
          </details>
        </fieldset>
        <button className="primary" type="submit" disabled={pending}>{pending ? "Calcul en cours…" : "Calculer mon résultat"}</button>
        {error && <p role="alert" className="error">{error}</p>}
      </form>
      <section className="ticket" aria-live="polite">
        <h2>Ticket de caisse comparatif</h2>
        {result ? <>
          <p className="stamp">🟡 Hypothèses de chiffrage</p>
          {changed && <p className="note">Le profil a changé. Relancez le calcul pour actualiser ce ticket.</p>}
          <div className="delta">
            <strong>{delta > 0 ? "+" : delta < 0 ? "−" : ""}{euros.format(Math.abs(delta))}</strong>
            <span> par mois de revenu disponible</span>
          </div>
          <table>
            <thead><tr><th>Poste</th><th>Gel</th><th>PLF</th></tr></thead>
            <tbody>{result.lignes.map((line) => <tr key={line.poste}>
              <th scope="row">{lines[line.poste]}</th><td>{amount(line.gel_eur)}</td><td>{amount(line.plf_eur)}</td>
            </tr>)}</tbody>
          </table>
          {taxChange && <p className="note"><strong>{taxChange.annual}</strong>{taxChange.monthly && `, ${taxChange.monthly}`}.</p>}
          {applied && <p className="note">Hypothèses utilisées. Zone {applied.zone_apl}, loyer {euros.format(applied.loyer_mensuel)}/mois
            {applied.revenu_brut_mensuel !== null && `, brut ${applied.brut_saisi ? "saisi" : "estimé"} ${euros.format(applied.revenu_brut_mensuel)}/mois`}.</p>}
          <details><summary>D’où sort ce chiffre&nbsp;?</summary>
            {result.hypotheses.map((assumption) => <p key={assumption}>{assumption}</p>)}
            <a href={result.source_ref} target="_blank" rel="noreferrer">PLF 2027 déposé, articles 2 et 3</a>
            <p><a href={result.source_loyer} target="_blank" rel="noreferrer">Référence du loyer par défaut</a></p>
          </details>
          <button className="share" type="button" onClick={share} disabled={sharing || changed}>
            {sharing ? "Préparation…" : "Télécharger Ma Carte 2027"}
          </button>
        </> : pending ? <div className="simulation-progress" role="status">
          <p>Simulation sur OpenFisca en cours…</p><div aria-hidden="true" className="simulation-progress-track" />
        </div> : <p>Renseignez votre foyer et lancez le calcul pour afficher les deux scénarios.</p>}
      </section>
    </div>
    <footer>Simulation pédagogique ex ante fondée sur le PLF déposé. Les montants sont indicatifs et ne constituent pas un avis fiscal.</footer>
  </main>;
}
