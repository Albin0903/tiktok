const euros = new Intl.NumberFormat("fr-FR", {style: "currency", currency: "EUR", maximumFractionDigits: 0});
const signedEuros = new Intl.NumberFormat("fr-FR", {style: "currency", currency: "EUR", maximumFractionDigits: 0, signDisplay: "exceptZero"});

export function describeTaxChange(delta: number) {
  const annual = Math.round(Math.abs(delta));
  return {
    annual: annual === 0 ? "Impôt annuel inchangé" : `${euros.format(annual)} de ${delta > 0 ? "plus" : "moins"} par an`,
    monthly: annual === 0 ? null : `soit ${signedEuros.format(delta / 12)} / mois`,
  };
}
