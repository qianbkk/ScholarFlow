// App root — wraps providers, renders the Workspace.

import { SearchProvider } from './contexts/SearchContext';
import { SelectionProvider } from './contexts/SelectionContext';
import { Workspace } from './pages/Workspace';

export function App() {
  return (
    <SearchProvider>
      <SelectionProvider>
        <Workspace />
      </SelectionProvider>
    </SearchProvider>
  );
}
