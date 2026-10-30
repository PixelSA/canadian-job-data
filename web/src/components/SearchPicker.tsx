import { useQuery } from "@tanstack/react-query"; // tanstack for data fetch/cache
import { getSearches, type SearchOut } from "../api";

// arguments for the component
type Props = {
  value: SearchOut | null; 
  onChange: (search: SearchOut) => void;
};

function label(s: SearchOut): string {
  const cap = (w: string) => w.charAt(0).toUpperCase() + w.slice(1);
  return `${cap(s.role)} · ${cap(s.region)}`;
}

export default function SearchPicker({ value, onChange }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["searches"],
    queryFn: getSearches,
  });

  if (isLoading) return <p>Waking up the server…</p>;
  if (isError || !data) return <p>Couldn't reach the API. Try refreshing.</p>;

  return (
    <label>
      Search{" "}
      <select
        value={value?.key ?? ""}
        onChange={(e) => {
          const picked = data.find((s) => s.key === e.target.value);
          if (picked) onChange(picked);
        }}
      >
        <option value="" disabled>Choose a role and region…</option>
        {data.map((s) => (
          <option key={s.key} value={s.key}>{label(s)}</option>
        ))}
      </select>
    </label>
  );
}