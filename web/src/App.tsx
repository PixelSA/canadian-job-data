import { useState } from "react";
import SearchPicker from "./components/SearchPicker";
import type { SearchOut } from "./api";

export default function App() {
  // The selected search lives here, because every chart and list will need it.
  const [search, setSearch] = useState<SearchOut | null>(null);

  return (
    <main>
      <h1>Canadian Job Market</h1>
      <SearchPicker value={search} onChange={setSearch} />

      {search ? (
        <p>Selected: {search.role} in {search.region}</p>
      ) : (
        <p>Pick a role and region to see the market.</p>
      )}
    </main>
  );
}