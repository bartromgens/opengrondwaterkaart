import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', loadComponent: () => import('./home/home').then((m) => m.HomeComponent) },
  { path: 'about', loadComponent: () => import('./about/about').then((m) => m.AboutComponent) },
];
