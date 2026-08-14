import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', loadComponent: () => import('./home/home').then((m) => m.HomeComponent) },
  {
    path: 'wells',
    loadComponent: () =>
      import('./wells-overview/wells-overview').then((m) => m.WellsOverviewComponent),
  },
  { path: 'about', loadComponent: () => import('./about/about').then((m) => m.AboutComponent) },
];
