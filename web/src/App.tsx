import { useState } from "react";
import SearchPicker from "./components/SearchPicker";
import ThemeToggle from "./components/ThemeToggle";
import TopSkills from "./components/TopSkills";
import DemandChart from "./components/DemandChart";
import SalaryRange from "./components/SalaryRange";
import TopCompanies from "./components/TopCompanies";
import PostingsList from "./components/PostingsList";
import type { SearchOut } from "./api";

export default function App() {
  const [search, setSearch] = useState<SearchOut | null>(null);

  return (
    <main>
      <header className="page-header">
        <div>
          <p className="eyebrow">Job market intelligence</p>
          <h1>Canadian Job Market</h1>
          <p className="lede">Trending skills, salaries and hiring demand, updated daily.</p>
        </div>
        <div className="controls">
          <SearchPicker value={search} onChange={setSearch} />
          <ThemeToggle />
        </div>
      </header>

      {search ? (
        <div className="grid">
          <div className="card wide"><TopSkills search={search} /></div>
          <div className="card"><SalaryRange search={search} /></div>
          <div className="card"><TopCompanies search={search} /></div>
          <div className="card full"><DemandChart search={search} /></div>
          {/* key: a new search remounts the list, so paging starts again at page 1 */}
          <div className="card full"><PostingsList key={search.key} search={search} /></div>
        </div>
      ) : (
        <p className="status">Pick a role and region to see the market.</p>
      )}

      <footer>
        Data: Job Bank open data (monthly), JSearch, Jobven and public company job boards.
        Daily figures count postings seen in the last two days.
      </footer>
    </main>
  );
}
