// Typescript equivalents of each schema
export type SearchOut = {
  key: string;      // "data analyst|alberta"
  role: string;
  region: string;
};

export type SkillOut = {
  skill: string;
  category: string;
  postings: number;
  share: number;          // 0–1, not a percentage
  change: number | null;  // vs. 7 days earlier; null when there's nothing to compare
};

export type SkillTrendsOut = {
  search: SearchOut;
  day: string | null;     // "2026-10-29"; null when the search has no daily stats yet
  skills: SkillOut[];
};

export type SalaryPointOut = {
    day: string;
    sample_size: number;
    p25: number | null;
    median: number | null;
    p75: number | null;
};


export type SalaryTrendsOut = {
    search: SearchOut;
    points: SalaryPointOut[]
};


export type DemandPointOut = {
    month: string;
    new_postings: number;
    vacancies: number;
    salary_sample_size: number;
    p25: number | null;
    median: number | null;
    p75: number | null;
    note: string | null;
};

export type DemandTrendsOut = {
    search: SearchOut;
    points: DemandPointOut[];
};

export type PostingOut = {
    title: string;
    company: string | null;
    location: string | null;
    url: string | null;
    salary_min: number | null;
    salary_max: number | null;
    salary_is_estimate: boolean;
    source: string;
    first_seen: string;
};

export type PostingsPage = {
    search: SearchOut;
    total: number;
    limit: number;
    offset: number;
    postings: PostingOut[];
};


export type CompanyOut = { 
    comapny: string;
    postings: number;
};

export type CompaniesOut = {
    search: SearchOut;
    companies: CompanyOut[];
}

// Helper function for using the API

const BASE = import.meta.env.VITE_API_URL;

async function get<T>(path: string, params: Record<string, string | number> = {}): Promise<T> {
  const url = new URL(path, BASE);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}

export const getSearches = () => get<SearchOut[]>("/searches");

export const getSkills = (role: string, region: string, limit = 15) =>
  get<SkillTrendsOut>("/trends/skills", { role, region, limit });

export const getSalaries = (role: string, region: string, days: number) => 
    get<SalaryTrendsOut>("/trends/salaries", {role, region, days});

export const getDemand = (role: string, region: string, since: number) =>
    get<DemandTrendsOut>("/trends/demand", {role, region, since});

export const getPostings = (role: string, region: string, limit: number, offset: number) =>
    get<PostingOut>("/postings", {role, region, limit, offset});

export const getCompanies = (role: string, region: string, limit: number) =>
    get<CompaniesOut>("/companies", {role, region, limit});
