// Games Repository (Supabase ready: table 'games')
export const GAMES = [
  { id: 'g1', name: 'Elden Ring: Shadow of the Erdtree', default_ps4_price: 35.00, default_ps5_price: 45.00 },
  { id: 'g2', name: 'God of War Ragnarok', default_ps4_price: 30.00, default_ps5_price: 40.00 },
  { id: 'g3', name: 'Gran Turismo 7', default_ps4_price: 25.00, default_ps5_price: 35.00 },
  { id: 'g4', name: 'Spider-Man 2', default_ps4_price: 35.00, default_ps5_price: 45.00 },
  { id: 'g5', name: 'Horizon Forbidden West', default_ps4_price: 25.00, default_ps5_price: 35.00 },
  { id: 'g6', name: 'The Last of Us Part I', default_ps4_price: 30.00, default_ps5_price: 40.00 },
  { id: 'g7', name: 'Ghost of Tsushima DC', default_ps4_price: 20.00, default_ps5_price: 30.00 },
  { id: 'g8', name: 'FC 25 (Standard)', default_ps4_price: 40.00, default_ps5_price: 50.00 },
  { id: 'g9', name: 'Call of Duty: Black Ops 6', default_ps4_price: 45.00, default_ps5_price: 55.00 },
  { id: 'g10', name: 'Resident Evil 4 Remake', default_ps4_price: 25.00, default_ps5_price: 35.00 },
];

export const ADMINS = [
  { id: 'adm1', name: 'Msaka', role: 'Super Admin' },
  { id: 'adm2', name: 'Dimitri', role: 'Super Admin' },
];

// Helper to generate a random account
const generateMockAccount = (id, email, region, status = 'active', condition = 'clean') => {
  const accountGames = [GAMES[Math.floor(Math.random() * GAMES.length)].id];
  if (Math.random() > 0.5) accountGames.push(GAMES[Math.floor(Math.random() * GAMES.length)].id);
  
  const purchaseCost = 40 + Math.random() * 30;
  const psnDeposits = 100 + Math.random() * 150;
  const psnGamePurchases = 120 + Math.random() * 50;

  // Slot generation
  const generateSlots = (console) => {
    return [
      { id: `${id}-${console}-1`, type: 'normal', status: Math.random() > 0.5 ? 'sold' : 'available', price: 0, customer: '', date: '' },
      { id: `${id}-${console}-2`, type: 'normal', status: Math.random() > 0.7 ? 'sold' : 'available', price: 0, customer: '', date: '' },
      { id: `${id}-${console}-3`, type: 'reset', status: 'locked', lastReset: null, nextReset: null },
    ];
  };

  return {
    id,
    email,
    password: `pass_${Math.random().toString(36).substring(7)}`,
    region,
    condition, // 'clean', 'warning', 'issue', 'archived'
    status, // 'active', 'unrecovered', 'sold_out'
    notes: 'Premium business asset.',
    purchaseCost,
    psnDeposits,
    psnGamePurchases,
    games: accountGames,
    slots: {
      ps4: generateSlots('ps4'),
      ps5: generateSlots('ps5'),
    },
    expenses: [],
    revenue: 0,
    lastDeactivation: null,
    nextDeactivation: null,
    createdAt: '2026-05-15'
  };
};

export const INITIAL_ACCOUNTS = [
  generateMockAccount('acc1', 'alex.gaming@psn.com', 'US', 'active', 'clean'),
  generateMockAccount('acc2', 'dimi.pro.slots@psn.com', 'UK', 'active', 'clean'),
  generateMockAccount('acc3', 'turbo.accounts@psn.com', 'TR', 'active', 'warning'),
  generateMockAccount('acc4', 'psn.vault.04@example.com', 'US', 'active', 'clean'),
  generateMockAccount('acc5', 'shadow.erdtree@psn.com', 'UK', 'active', 'clean'),
  generateMockAccount('acc6', 'fc25.central@psn.com', 'US', 'active', 'issue'),
  generateMockAccount('acc7', 'kratos.legacy@example.org', 'US', 'active', 'clean'),
  generateMockAccount('acc8', 'web.spinner.99@psn.com', 'UK', 'active', 'clean'),
  generateMockAccount('acc9', 'horizon.dawn@psn.com', 'TR', 'active', 'clean'),
  generateMockAccount('acc10', 'ghost.tsushima@psn.com', 'JP', 'active', 'clean'),
  generateMockAccount('acc11', 'cod.bo6.official@psn.com', 'US', 'active', 'clean'),
  generateMockAccount('acc12', 'resident.evil.vault@psn.com', 'UK', 'active', 'clean'),
  generateMockAccount('acc13', 'apex.predator@example.com', 'US', 'active', 'clean'),
  generateMockAccount('acc14', 'gt7.speed@psn.com', 'UK', 'active', 'clean'),
  generateMockAccount('acc15', 'last.of.us.re@psn.com', 'US', 'active', 'clean'),
  generateMockAccount('acc16', 'vintage.gamer@psn.com', 'US', 'active', 'archived'),
  generateMockAccount('acc17', 'recovering.asset@psn.com', 'UK', 'unrecovered', 'issue'),
  generateMockAccount('acc18', 'sold.out.king@psn.com', 'US', 'sold_out', 'clean'),
  generateMockAccount('acc19', 'newly.added@psn.com', 'TR', 'active', 'clean'),
  generateMockAccount('acc20', 'pro.slots.jp@psn.com', 'JP', 'active', 'clean'),
];

export const INITIAL_TRANSACTIONS = [
  { id: 't1', type: 'capital_in', amount: 5000.00, date: '2026-04-01', note: 'Q2 Business Injection', admin: 'Msaka' },
  { id: 't2', type: 'withdrawal', amount: 500.00, date: '2026-05-20', note: 'Monthly profit withdrawal', admin: 'Msaka' },
  { id: 't3', type: 'expense', amount: 15.00, date: '2026-06-01', note: 'Domain renewal', admin: 'Dimitri' },
  { id: 't4', type: 'adjustment', amount: 50.00, date: '2026-06-05', note: 'Inventory reconciliation', admin: 'Msaka' },
];
// Note: Slot sales will be generated dynamically or manually in the prototype
