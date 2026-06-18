// Tiny hook: subscribe to the store and re-render on any change.
import { useEffect, useState } from 'react';
import { store, type StoreState } from '../state/store';

export function useStore(): StoreState {
  const [s, setS] = useState<StoreState>(store.get());
  useEffect(() => {
    return store.subscribe(() => setS(store.get()));
  }, []);
  return s;
}
