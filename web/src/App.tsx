import { useState } from "react";
import SearchPicker from "./components/SearchPicker";
import TopSkills from "./components/TopSkills";
import DemandChart from "./components/DemandChart";
import type { SearchOut } from "./api";

export default function App() {
  const [search, setSearch] = useState<SearchOut | null>(null);

  return (
    <main>
      <h1>Canadian Job Market</h1>
      <SearchPicker value={search} onChange={setSearch} />

      {search ? (
        <>
          <TopSkills search={search} />
          <DemandChart search={search} />
        </>
      ) : (
        <p>Pick a role and region to see the market.</p>
      )}
    </main>
  );
}