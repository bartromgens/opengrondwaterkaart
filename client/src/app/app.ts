import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule, MatIconRegistry } from '@angular/material/icon';
import { DomSanitizer } from '@angular/platform-browser';

import { SeoService } from './seo.service';

@Component({
  selector: 'app-root',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatToolbarModule,
    MatButtonModule,
    MatIconModule,
  ],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private seo = inject(SeoService);

  constructor(matIconRegistry: MatIconRegistry, domSanitizer: DomSanitizer) {
    matIconRegistry.addSvgIcon('github', domSanitizer.bypassSecurityTrustResourceUrl('github.svg'));

    this.seo.setJsonLd('jsonld-webapplication', {
      '@context': 'https://schema.org',
      '@type': 'WebApplication',
      name: 'OpenGrondWaterKaart',
      description:
        'Interactieve kaart met actuele grondwaterstanden in Nederland, gebaseerd op open data van BRO en PDOK.',
      url: 'https://opengrondwaterkaart.nl/',
      applicationCategory: 'UtilitiesApplication',
      operatingSystem: 'Any',
      inLanguage: 'nl',
      isAccessibleForFree: true,
    });
  }
}
