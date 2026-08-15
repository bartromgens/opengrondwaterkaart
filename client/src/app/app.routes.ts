import { Routes } from '@angular/router';

import { adminGuard } from './admin.guard';

export const routes: Routes = [
  { path: '', loadComponent: () => import('./home/home').then((m) => m.HomeComponent) },
  {
    path: 'wells',
    loadComponent: () =>
      import('./wells-overview/wells-overview').then((m) => m.WellsOverviewComponent),
  },
  { path: 'about', loadComponent: () => import('./about/about').then((m) => m.AboutComponent) },
  {
    path: 'logs',
    loadComponent: () => import('./logs/logs').then((m) => m.LogsComponent),
    canActivate: [adminGuard],
  },
];
